from .applier_backend import applier_backend

import argparse

# Facility to determine GPTs for user
import optparse
from samba import getopt as options
from samba.gpclass import check_safe_path, check_refresh_gpo_list

# PReg object generator and parser
from samba.dcerpc import preg
from samba.dcerpc import misc
import samba.ndr

# This is needed to query AD DOMAIN name from LDAP
# using cldap_netlogon (and to replace netads utility
# invocation helper).
#from samba.dcerpc import netlogon

# This is needed by Registry.pol file search
import os
import re

# This is needed for Username and SID caching
import pickle

# Our native control facility
import util

# Internal error
import sys

from collections import OrderedDict

# Remove print() from code
import logging
logging.basicConfig(level=logging.DEBUG)

class samba_backend(applier_backend):
    __default_policy_path = '/usr/share/local-policy/default'
    _samba_registry_file = '/var/cache/samba/registry.tdb'
    _mahine_hive = 'HKEY_LOCAL_MACHINE'
    _user_hive = 'HKEY_CURRENT_USER'
    _machine_pol_path_pattern = '[Mm][Aa][Cc][Hh][Ii][Nn][Ee].*\.pol$'
    _user_pol_path_pattern = '[Uu][Ss][Ee][Rr].*\.pol$'

    def __init__(self, loadparm, creds, sid, dc, username):
        # Check if we're working for user or for machine
        self._is_machine_username = False
        if util.get_machine_name() == username:
            self._is_machine_username = True

        # Samba objects - LoadParm() and CredentialsOptions()
        self.loadparm = loadparm
        self.creds = creds
        self.dc = dc

        self.cache_dir = self.loadparm.get('cache directory')
        logging.debug('Cache directory is: {}'.format(self.cache_dir))

        # Regular expressions to split PReg files into user and machine parts
        self._machine_pol_path_regex = re.compile(self._machine_pol_path_pattern)
        self._user_pol_path_regex = re.compile(self._user_pol_path_pattern)

        # User SID to work with HKCU hive
        self.username = username
        self.sid = sid

        cache_file = os.path.join(self.cache_dir, 'cache.pkl')
        # Load PReg paths from cache at first
        self.cache = util.get_cache(cache_file, OrderedDict())

        # Get policies for machine at first.
        self.machine_policy_set = self.get_policy_set(util.get_machine_name(), True)

        self.user_policy_set = None
        # Load user GPT values in case user's name specified
        if not self._is_machine_username:
            self.user_policy_set = self.get_policy_set(self.username)

        # Re-cache the retrieved values
        util.dump_cache(cache_file, self.cache)

    def get_policy_set(self, username, include_local_policy=False):
        logging.info('Fetching and merging settings for user {}'.format(username))
        policy_files = self._get_pol(username)

        if include_local_policy:
            policy_files['machine_regpols'].insert(0, os.path.join(self.__default_policy_path, 'local.xml'))

        machine_entries = util.merge_polfiles(policy_files['machine_regpols'])
        user_entries = util.merge_polfiles(policy_files['user_regpols'])

        policy_set = dict({ 'machine': machine_entries, 'user': user_entries })
        return policy_set

    def get_values(self):
        '''
        Read data from PReg file and return list of NDR objects (samba.preg)
        '''
        return list(self.machine_policy_set['machine'].values())

    def get_user_values(self):
        return list(self.machine_policy_set['user'].values())

    def _find_regpol_files(self, gpt_path):
        '''
        Seek through SINGLE given GPT directory absolute path and return
        the dictionary of user's and machine's Registry.pol files.
        '''
        logging.debug('Finding regpols in: {}'.format(gpt_path))

        polfiles = dict({ 'machine_regpols': [], 'user_regpols': [] })
        full_traverse = util.traverse_dir(gpt_path)
        polfiles['machine_regpols'] = [fname for fname in full_traverse if self._machine_pol_path_regex.search(fname)]
        polfiles['user_regpols'] = [fname for fname in full_traverse if self._user_pol_path_regex.search(fname)]

        return polfiles

    def _check_sysvol_present(self, gpo):
        '''
        Check if there is SYSVOL path for GPO assigned
        '''
        if not gpo.file_sys_path:
            logging.warning('No SYSVOL entry assigned to GPO {}'.format(gpo.name))
            return False
        return True

    def _gpo_get_gpt_polfiles(self, gpo_obj):
        '''
        Find absolute path to SINGLE cached GPT directory and return
        dict of lists with PReg file paths.
        '''
        if self._check_sysvol_present(gpo_obj):
            logging.debug('Found SYSVOL entry {} for GPO {}'.format(gpo_obj.file_sys_path, gpo_obj.name))
            path = check_safe_path(gpo_obj.file_sys_path).upper()
            gpt_abspath = os.path.join(self.cache_dir, 'gpo_cache', path)
            logging.debug('Path: {}'.format(path))
            policy_files = self._find_regpol_files(gpt_abspath)

            return policy_files
        return dict({ 'machine_regpols': [], 'user_regpols': [] })

    def _get_pol(self, username):
        '''
        Get PReg file paths from GPTs for specified username.
        '''
        policy_files = OrderedDict({ 'machine_regpols': [], 'user_regpols': [] })

        try:
            gpos = util.get_gpo_list(self.dc, self.creds, self.loadparm, username)

            # GPT replication function
            try:
                check_refresh_gpo_list(self.dc, self.loadparm, self.creds, gpos)
            except:
                logging.error('Unable to replicate GPTs from {} for {}'.format(self.dc, username))

            for gpo in gpos:
                polfiles = self._gpo_get_gpt_polfiles(gpo)
                policy_files['machine_regpols'] += polfiles['machine_regpols']
                policy_files['user_regpols']    += polfiles['user_regpols']
            # Cache paths to PReg files
            self.cache[self.sid] = policy_files
        except:
            logging.error('Error fetching GPO list from {} for'.format(self.dc, username))
            if self.sid in self.cache:
                policy_files = self.cache[sid]
                logging.info('Got cached PReg files')

        logging.info('Machine .pol file set: {}'.format(policy_files['machine_regpols']))
        logging.info('User .pol file set: {}'.format(policy_files['user_regpols']))

        return policy_files

