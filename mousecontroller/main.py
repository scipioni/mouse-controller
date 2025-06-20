import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import time
import pygame
import signal
import sys
import os
import random
import subprocess
import logging
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('BT_HID_Mouse')

# Standard mouse HID descriptor
MOUSE_DESCRIPTOR = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)
    0x05, 0x09,        #     Usage Page (Button)
    0x19, 0x01,        #     Usage Minimum (1)
    0x29, 0x03,        #     Usage Maximum (3)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x95, 0x03,        #     Report Count (3)
    0x75, 0x01,        #     Report Size (1)
    0x81, 0x02,        #     Input (Data,Var,Abs)
    0x95, 0x01,        #     Report Count (1)
    0x75, 0x05,        #     Report Size (5)
    0x81, 0x01,        #     Input (Const,Array,Abs)
    0x05, 0x01,        #     Usage Page (Generic Desktop)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x02,        #     Report Count (2)
    0x81, 0x06,        #     Input (Data,Var,Rel)
    0xC0,              #   End Collection
    0xC0               # End Collection
])

class BTHIDMouseService:
    BUS_NAME = 'org.bluez'
    BASE_HID_UUID = '00001124-0000-1000-8000-00805f9b34fb'  # Base HID UUID

    def __init__(self):
        # Generate unique identifiers
        self.pid = os.getpid()
        self.random_suffix = random.randint(1000, 9999)
        self.unique_uuid = f"{self.BASE_HID_UUID[:-4]}{self.random_suffix:04x}"
        
        # Create unique paths
        self.AGENT_PATH = f"/org/bluez/agent/{self.pid}_{self.random_suffix}"
        self.HID_PATH = f"/org/bluez/hid/{self.pid}_{self.random_suffix}"
        
        # Initialize DBus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = None
        self.mainloop = GLib.MainLoop()
        self.profile_registered = False
        self.agent_registered = False
        self.bluez_available = False
        
        # Setup cleanup handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Initialize mouse input
        pygame.init()
        pygame.display.set_mode((1, 1))  # Tiny invisible window
        
        logger.info(f"Starting HID Mouse Service (PID: {self.pid})")
        logger.info(f"Agent Path: {self.AGENT_PATH}")
        logger.info(f"HID Path: {self.HID_PATH}")
        logger.info(f"Using UUID: {self.unique_uuid}")
        
        # Setup Bluetooth services
        self.setup_services()

    def run_bluetoothctl_command(self, command, timeout=5):
        """Execute bluetoothctl command and return output"""
        try:
            result = subprocess.run(
                ['bluetoothctl', *command.split()],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            logger.debug(f"bluetoothctl {command}: {result.stdout.strip()}")
            if result.stderr:
                logger.debug(f"Error: {result.stderr.strip()}")
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.warning(f"bluetoothctl command timed out: {command}")
            return ""
        except Exception as e:
            logger.error(f"Error running bluetoothctl: {e}")
            return ""

    def ensure_bluetooth_service(self):
        """Ensure Bluetooth service is running using bluetoothctl"""
        try:
            # Check if Bluetooth service is active
            status = self.run_bluetoothctl_command("show")
            if "Controller" not in status:
                logger.warning("Bluetooth service not responding. Restarting...")
                subprocess.run(['sudo', 'systemctl', 'restart', 'bluetooth'], check=True)
                time.sleep(2)  # Give service time to start
            
            # Ensure controller is powered on
            if "Powered: no" in status:
                logger.info("Powering on Bluetooth controller")
                self.run_bluetoothctl_command("power on")
                time.sleep(1)
            
            # Ensure controller is discoverable
            if "Discoverable: no" in status:
                logger.info("Enabling discoverable mode")
                self.run_bluetoothctl_command("discoverable on")
            
            # Ensure controller is pairable
            if "Pairable: no" in status:
                logger.info("Enabling pairable mode")
                self.run_bluetoothctl_command("pairable on")
            
            # Enable agent
            self.run_bluetoothctl_command("agent on")
            
            # Reset controller if needed
            if "Discoverable: no" in status or "Pairable: no" in status:
                self.run_bluetoothctl_command("scan off")
                self.run_bluetoothctl_command("scan on")
            
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Bluetooth service management failed: {e}")
            return False

    def get_dbus_connection(self):
        """Establish DBus connection with retry logic"""
        for attempt in range(3):
            try:
                logger.info(f"Connecting to system DBus (attempt {attempt+1}/3)")
                bus = dbus.SystemBus()
                # Verify BlueZ is available
                bluez_obj = bus.get_object('org.bluez', '/org/bluez')
                logger.info("DBus connection established successfully")
                return bus
            except dbus.exceptions.DBusException as e:
                logger.warning(f"DBus connection failed: {e}")
                if "org.freedesktop.DBus.Error.ServiceUnknown" in str(e):
                    if not self.ensure_bluetooth_service():
                        logger.error("Could not start Bluetooth service")
                time.sleep(2)
        raise ConnectionError("Could not establish DBus connection")

    def setup_services(self):
        """Setup Bluetooth agent and HID profile with robust error handling"""
        try:
            # Get DBus connection
            self.bus = self.get_dbus_connection()
            
            # Get BlueZ interfaces
            bluez_obj = self.bus.get_object(self.BUS_NAME, '/org/bluez')
            self.agent_manager = dbus.Interface(
                bluez_obj, 'org.bluez.AgentManager1'
            )
            self.profile_manager = dbus.Interface(
                bluez_obj, 'org.bluez.ProfileManager1'
            )
            
            # Register agent and profile with unique paths
            self.register_agent()
            self.register_profile()
            
        except (dbus.exceptions.DBusException, ConnectionError) as e:
            logger.error(f"Service setup error: {e}")
            self.cleanup()
            sys.exit(1)
    
    def register_agent(self):
        """Register Bluetooth agent for pairing with retry logic"""
        for attempt in range(3):
            try:
                logger.info(f"Registering agent (attempt {attempt+1}/3)")
                self.agent_manager.RegisterAgent(self.AGENT_PATH, "NoInputNoOutput")
                self.agent_manager.RequestDefaultAgent(self.AGENT_PATH)
                self.agent_registered = True
                logger.info("Bluetooth agent registered successfully")
                return
            except dbus.exceptions.DBusException as e:
                logger.warning(f"Agent registration failed: {e}")
                time.sleep(1)
        logger.error("Agent registration failed after 3 attempts")
        self.agent_registered = False
    
    def register_profile(self):
        """Register HID profile with unique UUID and retry logic"""
        for attempt in range(3):
            try:
                logger.info(f"Registering profile (attempt {attempt+1}/3)")
                self.profile_manager.RegisterProfile(
                    self.HID_PATH, self.unique_uuid, {
                        'Name': f'Python HID Mouse {self.random_suffix}',
                        'Role': 'server',
                        'RequireAuthentication': False,
                        'RequireAuthorization': False,
                        'AutoConnect': True,
                        'ServiceRecord': self.get_sdp_record()
                    }
                )
                self.profile_registered = True
                logger.info("HID profile registered successfully")
                return
            except dbus.exceptions.DBusException as e:
                logger.warning(f"Profile registration failed: {e}")
                
                # Handle specific errors
                if "org.bluez.Error.AlreadyExists" in str(e):
                    logger.info("Unregistering conflicting profile...")
                    try:
                        self.profile_manager.UnregisterProfile(self.HID_PATH)
                    except:
                        pass
                
                time.sleep(1)
        logger.error("Profile registration failed after 3 attempts")
        self.profile_registered = False
    
    def get_sdp_record(self):
        """Generate SDP record with unique identifiers"""
        return dbus.String(f"""
            <record>
                <attribute id="0x0001">
                    <sequence>
                        <uuid value="{self.unique_uuid}"/>
                    </sequence>
                </attribute>
                <attribute id="0x0004">
                    <sequence>
                        <sequence>
                            <uuid value="0x0100"/>
                        </sequence>
                        <sequence>
                            <uuid value="0x0011"/>
                        </sequence>
                    </sequence>
                </attribute>
                <attribute id="0x0005">
                    <sequence>
                        <uuid value="0x1002"/>
                    </sequence>
                </attribute>
                <attribute id="0x0009">
                    <sequence>
                        <sequence>
                            <uuid value="{self.unique_uuid}"/>
                        </sequence>
                    </sequence>
                </attribute>
                <attribute id="0x0100">
                    <text value="Python HID Mouse {self.random_suffix}"/>
                </attribute>
                <attribute id="0x0101">
                    <text value="Python Virtual Mouse {self.pid}"/>
                </attribute>
                <attribute id="0x0006">
                    <sequence>
                        <uint16 value="0x656e"/>
                        <uint16 value="0x006a"/>
                        <uint16 value="0x0100"/>
                    </sequence>
                </attribute>
            </record>
        """)
        
    def run(self):
        """Main loop to capture mouse input"""
        if not self.profile_registered:
            logger.error("Cannot run without HID profile")
            return
            
        logger.info("Mouse service running. Use Ctrl+C to stop.")
        logger.info("Make your device discoverable and pair with it from the target device.")
        
        prev_pos = pygame.mouse.get_pos()
        
        try:
            while True:
                time.sleep(0.01)  # Reduce CPU usage
                
                # Get current mouse state
                curr_pos = pygame.mouse.get_pos()
                left, middle, right = pygame.mouse.get_pressed()
                
                # Calculate delta movement
                dx = max(-127, min(127, curr_pos[0] - prev_pos[0]))
                dy = max(-127, min(127, curr_pos[1] - prev_pos[1]))
                prev_pos = curr_pos
                
                # Pack HID report (buttons + dx/dy)
                buttons = (left | (right << 1) | (middle << 2))
                report = bytes([buttons, dx & 0xFF, dy & 0xFF])
                
                # In a real implementation, you would send this report to connected devices
                if dx != 0 or dy != 0 or buttons != 0:
                    logger.debug(f"Mouse report: buttons={buttons}, dx={dx}, dy={dy}")
                
        except KeyboardInterrupt:
            logger.info("Stopping mouse capture...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.cleanup()
            
    def signal_handler(self, signum, frame):
        """Handle system signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.cleanup()
        sys.exit(0)
        
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        
        # Unregister Bluetooth services
        if hasattr(self, 'profile_manager') and self.profile_registered:
            try:
                self.profile_manager.UnregisterProfile(self.HID_PATH)
                logger.info("Unregistered HID profile")
            except dbus.exceptions.DBusException as e:
                logger.error(f"Profile unregister error: {e}")
            
        if hasattr(self, 'agent_manager') and self.agent_registered:
            try:
                self.agent_manager.UnregisterAgent(self.AGENT_PATH)
                logger.info("Unregistered Bluetooth agent")
            except dbus.exceptions.DBusException as e:
                logger.error(f"Agent unregister error: {e}")
            
        # Clean up pygame
        pygame.quit()
        
        # Stop main loop if running
        if hasattr(self, 'mainloop') and self.mainloop.is_running():
            self.mainloop.quit()

def setup_environment():
    """Prepare the system environment for Bluetooth HID using bluetoothctl"""
    logger.info("Preparing system environment with bluetoothctl...")
    
    # Load required kernel modules
    subprocess.run(['sudo', 'modprobe', 'hidp'], check=False)
    subprocess.run(['sudo', 'modprobe', 'bluetooth'], check=False)
    subprocess.run(['sudo', 'modprobe', 'btusb'], check=False)
    
    # Enable Bluetooth experimental features
    with open('/etc/bluetooth/main.conf', 'a') as f:
        f.write("\n# Added by Python HID Mouse\n")
        f.write("Experimental = true\n")
        f.write("KernelExperimental = true\n")
    
    # Restart Bluetooth service
    subprocess.run(['sudo', 'systemctl', 'restart', 'bluetooth'], check=True)
    time.sleep(2)
    
    # Use bluetoothctl to configure the adapter
    def run_ctl_command(cmd):
        subprocess.run(
            ['sudo', 'bluetoothctl', *cmd.split()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    
    # Configure Bluetooth controller
    run_ctl_command("power on")
    run_ctl_command("discoverable on")
    run_ctl_command("pairable on")
    run_ctl_command("agent on")
    
    # Show final status
    result = subprocess.run(
        ['sudo', 'bluetoothctl', 'show'],
        capture_output=True,
        text=True
    )
    logger.info("Bluetooth controller status:")
    for line in result.stdout.splitlines():
        if any(key in line for key in ["Powered", "Discoverable", "Pairable"]):
            logger.info(f"  {line.strip()}")
    
    logger.info("Environment setup complete")

def get_bluetooth_address():
    """Get the Bluetooth MAC address using bluetoothctl"""
    try:
        result = subprocess.run(
            ['bluetoothctl', 'list'],
            capture_output=True,
            text=True,
            check=True
        )
        # Extract MAC address from output
        match = re.search(r'([0-9A-Fa-f]{2}[:]){5}([0-9A-Fa-f]{2})', result.stdout)
        if match:
            return match.group(0)
        return "UNKNOWN"
    except Exception as e:
        logger.error(f"Error getting Bluetooth address: {e}")
        return "UNKNOWN"

def print_pairing_instructions():
    """Print user-friendly pairing instructions"""
    address = get_bluetooth_address()
    print("\n" + "="*60)
    print("Bluetooth HID Mouse Setup Complete!")
    print("="*60)
    print("To pair your device:")
    print(f"1. On your target device (computer/tablet/phone), go to Bluetooth settings")
    print(f"2. Look for a device named 'Python HID Mouse'")
    print(f"3. Select and pair with the device")
    print(f"4. No PIN is required")
    print("\nTroubleshooting Tips:")
    print(f"- Ensure Bluetooth is enabled on this device (MAC: {address})")
    print("- Restart Bluetooth on both devices if pairing fails")
    print("- Run 'sudo systemctl restart bluetooth' if needed")
    print("="*60 + "\n")

def main():
    # Check if we have root privileges
    if os.geteuid() != 0:
        logger.error("Please run with sudo:")
        logger.error(f"sudo python3 {sys.argv[0]}")
        sys.exit(1)
    
    # Set up system environment
    setup_environment()
    
    # Create and run mouse service
    mouse = BTHIDMouseService()
    
    # Print pairing instructions
    print_pairing_instructions()
    
    mouse.run()

if __name__ == "__main__":
    main()