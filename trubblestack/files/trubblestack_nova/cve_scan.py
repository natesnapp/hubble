# -*- encoding: utf-8 -*-
'''
TrubbleStack Nova plugin for openscap scanning.
'''
from __future__ import absolute_import
import salt.utils
import salt.utils.path
import logging

log = logging.getLogger(__name__)


def __virtual__():
    if salt.utils.platform.is_linux() and salt.utils.path.which('oscap'):
        return True
    return False, 'This module requires Linux and the oscap binary'


def audit(data_list, tags, labels, debug=False, **kwargs):
    '''
    Run the network.netstat command
    '''
    ret = {'Success': [], 'Failure': []}

    __tags__ = []
    __feed__ = []
    for data in data_list:
        if 'cve_scan' in data:
            __tags__ = ['cve_scan']
            if isinstance(data['cve_scan'], str):
                __feed__.append(data['cve_scan'])
            else:  # assume list
                __feed__.extend(data['cve_scan'])

    if not __tags__:
        # No yaml data found, don't do any work
        return ret

    for feed in __feed__:
        ret['Failure'].append(__salt__['oscap.scan'](feed))
    return ret
