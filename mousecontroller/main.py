import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import time
import pygame
from mouse_descriptor import MOUSE_DESCRIPTOR

class BTHIDMouseService(dbus.service.Object):
    BUS_NAME = 'org.bluez'
    AGENT_PATH = '/org/bluez/agent'
    HID_PATH = '/org/bluez/hid'

    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        
        # Setup agent and profile manager
        self.setup_agent()
        self.setup_profile_manager()
        
        # Setup HID service
        self.setup_hid_service()
        
        # Initialize mouse input
        pygame.init()
        pygame.display.set_mode((1, 1))  # Tiny invisible window
        
    def setup_agent(self):
        """Setup Bluetooth agent for pairing"""
        agent_manager = dbus.Interface(
            self.bus.get_object(self.BUS_NAME, '/org/bluez'),
            'org.bluez.AgentManager1'
        )
        agent_manager.RegisterAgent(self.AGENT_PATH, "NoInputNoOutput")
        agent_manager.RequestDefaultAgent(self.AGENT_PATH)
        
    def setup_profile_manager(self):
        """Setup HID profile"""
        profile_manager = dbus.Interface(
            self.bus.get_object(self.BUS_NAME, '/org/bluez'),
            'org.bluez.ProfileManager1'
        )
        profile_manager.RegisterProfile(
            self.HID_PATH, '00001124-0000-1000-8000-00805f9b34fb', {
                'Name': 'HID Mouse',
                'Role': 'server',
                'RequireAuthentication': False,
                'RequireAuthorization': False,
                'AutoConnect': True,
                'ServiceRecord': self.get_sdp_record()
            }
        )
        
    def get_sdp_record(self):
        """Generate SDP record for HID mouse"""
        return """
            <record>
                <attribute id="0x0001">
                    <sequence>
                        <uuid value="0x1124"/>
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
                <attribute id="0x0006">
                    <sequence>
                        <uint16 value="0x656e"/>
                        <uint16 value="0x006a"/>
                        <uint16 value="0x0100"/>
                    </sequence>
                </attribute>
                <attribute id="0x0009">
                    <sequence>
                        <sequence>
                            <uuid value="0x1124"/>
                        </sequence>
                    </sequence>
                </attribute>
                <attribute id="0x0100">
                    <text value="HID Mouse"/>
                </attribute>
            </record>
        """
        
    def setup_hid_service(self):
        """Setup HID service characteristics"""
        service_manager = dbus.Interface(
            self.bus.get_object(self.BUS_NAME, '/org/bluez/hci0'),
            'org.bluez.GattManager1'
        )
        
        # This would need proper GATT service setup
        # Implementation omitted for brevity
        
    def run(self):
        """Main loop to capture mouse input and send HID reports"""
        prev_pos = pygame.mouse.get_pos()
        mainloop = GLib.MainLoop()
        
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
                
                # Here you would send the report over Bluetooth
                # Implementation depends on your Bluetooth stack
                self.send_hid_report(report)
                
        except KeyboardInterrupt:
            print("Shutting down...")
        finally:
            mainloop.quit()
            pygame.quit()
            
    def send_hid_report(self, report):
        """Send HID report to connected device"""
        # Actual implementation would use DBus or sockets to send
        # This is just a placeholder
        pass

def main():
    mouse = BTHIDMouseService()
    mouse.run()

if __name__ == "__main__":
    mouse()
