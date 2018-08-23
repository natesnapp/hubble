# -*- coding: utf-8 -*-
'''
osquery wrapper for TrubbleStack Nebula

Designed to run sets of osquery queries defined in pillar. These sets will have
a unique identifier, and be targeted by identifier. Usually, this identifier
will be a frequency. ('15 minutes', '1 day', etc). Identifiers are
case-insensitive.

You can then use the scheduler of your choice to run sets os queries at
whatever frequency you choose.

Sample pillar data:

nebula_osquery:
  hour:
    - crontab: query: select c.*,t.iso_8601 as _time from crontab as c join time as t;
    - query_name: suid_binaries
      query: select sb.*, t.iso_8601 as _time from suid_bin as sb join time as t;
  day:
    - query_name: rpm_packages
      query: select rpm.*, t.iso_8601 from rpm_packages as rpm join time as t;
'''
from __future__ import absolute_import

import copy
import json
import logging
import os
import re
import time
import yaml
import collections

import salt.utils
import salt.utils.platform
from salt.exceptions import CommandExecutionError
from trubblestack import __version__
import trubblestack.splunklogging

log = logging.getLogger(__name__)

__virtualname__ = 'nebula'


def __virtual__():
    return __virtualname__


def queries(query_group,
            query_file=None,
            verbose=False,
            report_version_with_day=True,
            topfile_for_mask=None,
            mask_passwords=False):
    '''
    Run the set of queries represented by ``query_group`` from the
    configuration in the file query_file

    query_group
        Group of queries to run

    query_file
        salt:// file which will be parsed for osquery queries

    verbose
        Defaults to False. If set to True, more information (such as the query
        which was run) will be included in the result.

    topfile_for_mask
        This is the location of the top file from which the masking information 
        will be extracted.
        
    mask_passwords
        Defaults to False. If set to True, passwords mentioned in the 
        return object are masked.
        
    CLI Examples:

    .. code-block:: bash

        salt '*' nebula.queries day
        salt '*' nebula.queries hour verbose=True
        salt '*' nebula.queries hour pillar_key=sec_osqueries
    '''
    query_data = {}
    MAX_FILE_SIZE = 104857600
    if query_file is None:
        if salt.utils.platform.is_windows():
            query_file = 'salt://trubblestack_nebula_v2/trubblestack_nebula_win_queries.yaml'
        else:
            query_file = 'salt://trubblestack_nebula_v2/trubblestack_nebula_queries.yaml'
    if not isinstance(query_file, list):
        query_file = [query_file]
    for fh in query_file:
        if 'salt://' in fh:
            orig_fh = fh
            fh = __salt__['cp.cache_file'](fh)
        if fh is None:
            log.error('Could not find file {0}.'.format(orig_fh))
            return None
        if os.path.isfile(fh):
            with open(fh, 'r') as f:
                f_data = yaml.safe_load(f)
                if not isinstance(f_data, dict):
                    raise CommandExecutionError('File data is not formed as a dict {0}'
                                                .format(f_data))
                query_data = _dict_update(query_data,
                                          f_data,
                                          recursive_update=True,
                                          merge_lists=True)

    if 'osquerybinpath' not in __grains__:
        if query_group == 'day':
            log.warning('osquery not installed on this host. Returning baseline data')
            # Match the formatting of normal osquery results. Not super
            #   readable, but just add new dictionaries to the list as we need
            #   more data
            ret = []
            ret.append(
                {'fallback_osfinger': {
                 'data': [{'osfinger': __grains__.get('osfinger', __grains__.get('osfullname')),
                           'osrelease': __grains__.get('osrelease', __grains__.get('lsb_distrib_release'))}],
                 'result': True
                 }}
            )
            if 'pkg.list_pkgs' in __salt__:
                ret.append(
                    {'fallback_pkgs': {
                     'data': [{'name': k, 'version': v} for k, v in __salt__['pkg.list_pkgs']().iteritems()],
                     'result': True
                     }}
                )
            uptime = __salt__['status.uptime']()
            if isinstance(uptime, dict):
                uptime = uptime.get('seconds', __salt__['cmd.run']('uptime'))
            ret.append(
                {'fallback_uptime': {
                 'data': [{'uptime': uptime}],
                 'result': True
                 }}
            )
            if report_version_with_day:
                ret.append(trubble_versions())
            return ret
        else:
            log.debug('osquery not installed on this host. Skipping.')
            return None

    query_data = query_data.get(query_group, {})

    if not query_data:
        return None

    ret = []
    timing = {}
    schedule_time = time.time()
    success = True
    for name, query in query_data.iteritems():
        query['query_name'] = name
        query_sql = query.get('query')
        if not query_sql:
            continue

        # Run the osqueryi query
        query_ret = {
            'result': True,
        }

        cmd = [__grains__['osquerybinpath'], '--read_max', MAX_FILE_SIZE, '--json', query_sql]
        t0 = time.time()
        res = __salt__['cmd.run_all'](cmd, timeout=10000)
        t1 = time.time()
        timing[name] = t1-t0
        if res['retcode'] == 0:
            query_ret['data'] = json.loads(res['stdout'])
        else:
            if "Timed out" in res['stdout']:
                # this is really the best way to tell without getting fancy
                log.error("TIMEOUT during osqueryi execution name=%s", name)
            success = False
            query_ret['result'] = False
            query_ret['error'] = res['stderr']

        if verbose:
            tmp = copy.deepcopy(query)
            tmp['query_result'] = query_ret
            ret.append(tmp)
        else:
            ret.append({name: query_ret})

    if success is False and salt.utils.platform.is_windows():
        log.error('osquery does not run on windows versions earlier than Server 2008 and Windows 7')
        if query_group == 'day':
            ret = []
            ret.append(
                {'fallback_osfinger': {
                 'data': [{'osfinger': __grains__.get('osfinger', __grains__.get('osfullname')),
                           'osrelease': __grains__.get('osrelease', __grains__.get('lsb_distrib_release'))}],
                 'result': True
                 }}
            )
            ret.append(
                {'fallback_error': {
                 'data': 'osqueryi is installed but not compatible with this version of windows',
                         'result': True
                 }}
            )
            return ret
        else:
            return None

    if __salt__['config.get']('splunklogging', False):
        log.info('Logging osquery timing data to splunk')
        trubblestack.splunklogging.__grains__ = __grains__
        trubblestack.splunklogging.__salt__ = __salt__
        trubblestack.splunklogging.__opts__ = __opts__
        handler = trubblestack.splunklogging.SplunkHandler()
        timing_data = {'query_run_length': timing,
                       'schedule_time' : schedule_time}
        handler.emit_data(timing_data)

    if query_group == 'day' and report_version_with_day:
        ret.append(trubble_versions())

    for r in ret:
        for query_name, query_ret in r.iteritems():
            if 'data' in query_ret:
                for result in query_ret['data']:
                    for key, value in result.iteritems():
                        if value and isinstance(value, basestring) and value.startswith('__JSONIFY__'):
                            result[key] = json.loads(value[len('__JSONIFY__'):])

    if mask_passwords:
        mask_passwords_inplace(ret, topfile_for_mask)
    return ret


def fields(*args):
    '''
    Use config.get to retrieve custom data based on the keys in the `*args`
    list.

    Arguments:

    *args
        List of keys to retrieve
    '''
    ret = {}
    for field in args:
        ret['custom_{0}'.format(field)] = __salt__['config.get'](field)
    # Return it as nebula data
    if ret:
        return [{'custom_fields': {
                 'data': [ret],
                 'result': True
                 }}]
    return []


def version():
    '''
    Report version of this module
    '''
    return __version__


def trubble_versions():
    '''
    Report version of all trubble modules as query
    '''
    versions = {'nova': __version__,
                'nebula': __version__,
                'pulsar': __version__,
                'quasar': __version__}

    return {'trubble_versions': {'data': [versions],
                                'result': True}}


def top(query_group,
        topfile='salt://trubblestack_nebula_v2/top.nebula',
        topfile_for_mask=None,
        verbose=False,
        report_version_with_day=True,
        mask_passwords=False):

    if salt.utils.platform.is_windows():
        topfile = 'salt://trubblestack_nebula_v2/win_top.nebula'

    configs = get_top_data(topfile)

    configs = ['salt://trubblestack_nebula_v2/' + config.replace('.', '/') + '.yaml'
               for config in configs]

    return queries(query_group,
                   query_file=configs,
                   verbose=False,
                   report_version_with_day=True,
                   topfile_for_mask=topfile_for_mask,
                   mask_passwords=mask_passwords)


def get_top_data(topfile):

    topfile = __salt__['cp.cache_file'](topfile)

    try:
        with open(topfile) as handle:
            topdata = yaml.safe_load(handle)
    except Exception as e:
        raise CommandExecutionError('Could not load topfile: {0}'.format(e))

    if not isinstance(topdata, dict) or 'nebula' not in topdata or \
            not(isinstance(topdata['nebula'], list)):
        raise CommandExecutionError('Nebula topfile not formatted correctly. '
                                    'Note that under the "nebula" key the data '
                                    'should now be formatted as a list of '
                                    'single-key dicts.')

    topdata = topdata['nebula']

    ret = []

    for topmatch in topdata:
        for match, data in topmatch.iteritems():
            if __salt__['match.compound'](match):
                ret.extend(data)

    return ret

def mask_passwords_inplace(object_to_be_masked, topfile):
    '''
    It masks the passwords present in 'object_to_be_masked'. Uses mask configuration
    file as a reference to find out the list of blacklisted strings or objects.
    Note that this method alters "object_to_be_masked".
    
    The path to the mask configuration file can be specified in the "topfile" 
    argument.
    '''
    try:

        mask = {}
        if topfile is None:
            topfile = 'salt://trubblestack_nebula_v2/top.mask'
        mask_files = get_top_data(topfile)
        mask_files = ['salt://trubblestack_nebula_v2/' + mask_file.replace('.', '/') + '.yaml'
                   for mask_file in mask_files]
        if mask_files is None:
            mask_files = 'salt://trubblestack_nebula_v2/mask.yaml'
        if not isinstance(mask_files, list):
            mask_files = [mask_files]
        for fh in mask_files:
            if 'salt://' in fh:
                orig_fh = fh
                fh = __salt__['cp.cache_file'](fh)
            if fh is None:
                log.error('Could not find file {0}.'.format(orig_fh))
                return None
            if os.path.isfile(fh):
                with open(fh, 'r') as f:
                    f_data = yaml.safe_load(f)
                    if not isinstance(f_data, dict):
                        raise CommandExecutionError('File data is not formed as a dict {0}'
                                                    .format(f_data))
                    mask = _dict_update(mask, f_data, recursive_update=True, merge_lists=True)

        log.debug("Using the mask: {}".format(mask))
        mask_by = mask.get('mask_by', '******')

        for blacklisted_string in mask.get("blacklisted_strings", []):
            query_name = blacklisted_string['query_name']
            column = blacklisted_string['column']
            if query_name != '*':
                for r in object_to_be_masked:
                    for query_result in r.get(query_name, {'data':[]})['data']:
                        if column not in query_result or not isinstance(query_result[column], basestring):
                            # if the column in not present in one data-object, it will 
                            # not be present in others as well. Break in that case.
                            # This will happen only if mask.yaml is malformed
                            break
                        value = query_result[column]
                        for pattern in blacklisted_string['blacklisted_patterns']:
                            value = re.sub(pattern + "()", r"\1" + mask_by + r"\3", value)
                        query_result[column] = value
            else:
                for r in object_to_be_masked:
                    for query_name, query_ret in r.iteritems():
                        for query_result in query_ret['data']:
                            if column not in query_result or not isinstance(query_result[column], basestring):
                                break
                            value = query_result[column]
                            for pattern in blacklisted_string['blacklisted_patterns']:
                                value = re.sub(pattern + "()", r"\1" + mask_by + r"\3", value)
                            query_result[column] = value


        for blacklisted_object in mask.get("blacklisted_objects", []):
            query_name = blacklisted_object['query_name']
            column = blacklisted_object['column']
            if query_name != '*':
                for r in object_to_be_masked:
                    for query_result in r.get(query_name, {'data':[]})['data']:
                        if column not in query_result or \
                        (isinstance(query_result[column], basestring) and query_result[column].strip() != '' ):
                            break
                        _recursively_mask_objects(query_result[column], blacklisted_object, mask_by)
            else:
                for r in object_to_be_masked:
                    for query_name, query_ret in r.iteritems():
                        for query_result in query_ret['data']:
                            if column not in query_result or \
                            (isinstance(query_result[column], basestring) and query_result[column].strip() != '' ):
                                break
                            _recursively_mask_objects(query_result[column], blacklisted_object, mask_by)
                                            
            # successfully masked the object. No need to return anything
        
    except Exception as e:
        log.exception("An error occured while masking the passwords: {}".format(e))

def _recursively_mask_objects(object_to_mask, blacklisted_object, mask_by):
    '''
    This function is used by "mask_passwords_inplace" to mask passwords contained in
    json objects or json arrays. If the "object_to_mask" is a json array, then this 
    function is called recursively on the individual members of the array.
 
     object_to_mask
        Json object/array whose elements are to masked recursively
        
     blacklisted_object
        This parameters contains info about which queries are to be masked, which 
        attributes are to be masked, based upon the value of which attribute.
        See trubblestack_nebula_v2/mask.yaml for exact format.
        
    mask_by
        If a password string is detected, it is replaced by the value of "mask_by" 
        parameter.
        
    '''
    if isinstance(object_to_mask, list):
        for child in object_to_mask:
            _recursively_mask_objects(child, blacklisted_object, mask_by)
    elif blacklisted_object['attribute_to_check'] in object_to_mask and \
         object_to_mask[blacklisted_object['attribute_to_check']] in blacklisted_object['blacklisted_patterns']:
        for key in blacklisted_object['attributes_to_mask']:
            if key in object_to_mask:
                object_to_mask[key] = mask_by


def _dict_update(dest, upd, recursive_update=True, merge_lists=False):
    '''
    Recursive version of the default dict.update

    Merges upd recursively into dest

    If recursive_update=False, will use the classic dict.update, or fall back
    on a manual merge (helpful for non-dict types like FunctionWrapper)

    If merge_lists=True, will aggregate list object types instead of replace.
    This behavior is only activated when recursive_update=True. By default
    merge_lists=False.
    '''
    if (not isinstance(dest, collections.Mapping)) \
            or (not isinstance(upd, collections.Mapping)):
        raise TypeError('Cannot update using non-dict types in dictupdate.update()')
    updkeys = list(upd.keys())
    if not set(list(dest.keys())) & set(updkeys):
        recursive_update = False
    if recursive_update:
        for key in updkeys:
            val = upd[key]
            try:
                dest_subkey = dest.get(key, None)
            except AttributeError:
                dest_subkey = None
            if isinstance(dest_subkey, collections.Mapping) \
                    and isinstance(val, collections.Mapping):
                ret = _dict_update(dest_subkey, val, merge_lists=merge_lists)
                dest[key] = ret
            elif isinstance(dest_subkey, list) \
                    and isinstance(val, list):
                if merge_lists:
                    dest[key] = dest.get(key, []) + val
                else:
                    dest[key] = upd[key]
            else:
                dest[key] = upd[key]
        return dest
    else:
        try:
            for k in upd.keys():
                dest[k] = upd[k]
        except AttributeError:
            # this mapping is not a dict
            for k in upd:
                dest[k] = upd[k]
        return dest
