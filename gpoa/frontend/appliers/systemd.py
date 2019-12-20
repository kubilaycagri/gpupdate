import dbus
import logging

class systemd_unit:
    def __init__(self, unit_name, state):
        self.system_bus = dbus.SystemBus()
        self.systemd_dbus = self.system_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        self.manager = dbus.Interface(self.systemd_dbus, 'org.freedesktop.systemd1.Manager')

        self.unit_name = unit_name
        self.desired_state = state
        self.unit = self.manager.LoadUnit(dbus.String(self.unit_name))
        self.unit_proxy = self.system_bus.get_object('org.freedesktop.systemd1', str(self.unit))
        self.unit_interface = dbus.Interface(self.unit_proxy, dbus_interface='org.freedesktop.systemd1.Unit')
        self.unit_properties = dbus.Interface(self.unit_proxy, dbus_interface='org.freedesktop.DBus.Properties')

    def apply(self):
        if self.desired_state == 1:
            self.manager.UnmaskUnitFiles([self.unit_name], dbus.Boolean(False))
            self.manager.EnableUnitFiles([self.unit_name], dbus.Boolean(False), dbus.Boolean(True))
            self.manager.StartUnit(self.unit_name, 'replace')
            logging.info('Starting systemd unit: {}'.format(self.unit_name))
            if self._get_state() != 'active':
                logging.error('Unable to start systemd unit {}'.format(self.unit_name))
        else:
            self.manager.StopUnit(self.unit_name, 'replace')
            self.manager.DisableUnitFiles([self.unit_name], dbus.Boolean(False))
            self.manager.MaskUnitFiles([self.unit_name], dbus.Boolean(False), dbus.Boolean(True))
            logging.info('Stopping systemd unit: {}'.format(self.unit_name))
            if self._get_state() != 'stopped':
                logging.error('Unable to stop systemd unit {}'.format(self.unit_name))

    def _get_state(self):
        '''
        Get the string describing service state.
        '''
        return self.unit_properties.Get('org.freedesktop.systemd1.Unit', 'ActiveState')
