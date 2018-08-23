import sys
import os
myPath = os.path.abspath(os.getcwd())
sys.path.insert(0, myPath)
import trubblestack.extmods.modules.nebula_osquery


class TestNebula():

    def test__virtual__(self):
        var = trubblestack.extmods.modules.nebula_osquery.__virtual__()
        assert var == 'nebula'

    def test_trubble_versions(self):
        var = trubblestack.extmods.modules.nebula_osquery.trubble_versions()
        assert ((var.get('trubble_versions')).get('result')) is True

    def test_queries(self):
        query_group = 'day'
        query_file = 'tests/unittests/resources/trubblestack_nebula_queries.yaml'

        def cp_cache_file(queryFile):
            return 'tests/unittests/resources/trubblestack_nebula_queries.yaml'

        def uptime():
            return {}

        def cmd_run(default):
            return default
        __salt__ = {}
        __salt__['cp.cache_file'] = cp_cache_file
        __salt__['status.uptime'] = uptime
        __salt__['cmd.run'] = cmd_run
        trubblestack.extmods.modules.nebula_osquery.__salt__ = __salt__
        trubblestack.extmods.modules.nebula_osquery.__grains__ = {'osfinger': 'Ubuntu-16.04'}

        def cmd_run_all(cmd):
            return {'retcode': 0, 'pid': 3478,
                    'stdout': '[{"build":"","codename":"xenial","major":"16","minor":"4","name":"Ubuntu","patch":"",'
                              '"platform":"ubuntu","platform_like":"debian","query_time":"1500395829","version":"16.04.2 LTS (Xenial Xerus)"}]',
                    'stderr': ''}
        __salt__['cmd.run_all'] = cmd_run_all
        var = trubblestack.extmods.modules.nebula_osquery.queries(query_group, query_file, verbose=False, report_version_with_day=False)
        assert len(var) != 0
        assert var[0]['fallback_osfinger']['data'][0]['osfinger'] == 'Ubuntu-16.04'

    def test_queries_for_report_version_with_day(self):
        query_group = 'day'
        query_file = 'tests/unittests/resources/trubblestack_nebula_queries.yaml'

        def cp_cache_file(queryFile):
            return 'tests/unittests/resources/trubblestack_nebula_queries.yaml'

        def uptime():
            return {}

        def cmd_run(default):
            return default
        __salt__ = {}
        __salt__['cp.cache_file'] = cp_cache_file
        __salt__['status.uptime'] = uptime
        __salt__['cmd.run'] = cmd_run
        trubblestack.extmods.modules.nebula_osquery.__salt__ = __salt__
        trubblestack.extmods.modules.nebula_osquery.__grains__ = {'osfinger': 'Ubuntu-16.04'}

        def cmd_run_all(cmd):
            return {'retcode': 0, 'pid': 3478,
                    'stdout': '[{"build":"","codename":"xenial","major":"16","minor":"4","name":"Ubuntu","patch":"",'
                              '"platform":"ubuntu","platform_like":"debian","query_time":"1500395829","version":"16.04.2 LTS (Xenial Xerus)"}]',
                    'stderr': ''}
        __salt__['cmd.run_all'] = cmd_run_all
        trubblestack.extmods.modules.nebula_osquery.__salt__ = __salt__
        var = trubblestack.extmods.modules.nebula_osquery.queries(query_group, query_file, verbose=False, report_version_with_day=True)
        trubblestack.extmods.modules.nebula_osquery.__salt__ = {}
        assert len(var) != 0
        assert (var[2]['trubble_versions']) is not None

    def test_trubble_version(self):
        var = trubblestack.extmods.modules.nebula_osquery.trubble_versions()
        assert (var['trubble_versions']) is not None

    def test_top(self):
        __salt__ = {}
        query_group = 'day'
        topfile = 'tests/unittests/resources/top.nebula'
        verbose = False,
        report_version_with_day = True

        def cp_cache_file(queryFile):
            return 'tests/unittests/resources/top.nebula'

        def match_compound(value):
            return value

        def status_uptime():
            return {}

        def cmd_run(default):
            return default
        __salt__['status.uptime'] = status_uptime
        __salt__['cmd.run'] = cmd_run
        __salt__['cp.cache_file'] = cp_cache_file
        __salt__['match.compound'] = match_compound
        trubblestack.extmods.modules.nebula_osquery.__salt__ = __salt__
        var = trubblestack.extmods.modules.nebula_osquery.top(query_group, topfile, verbose, report_version_with_day)
        trubblestack.extmods.modules.nebula_osquery.__salt__ = {}
        assert len(var) != 0
        assert var[0]['fallback_osfinger']['data'][0]['osfinger'] == 'Ubuntu-16.04'
