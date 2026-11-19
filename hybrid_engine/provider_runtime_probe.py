"""Synthetic-provider + real PTB loopback resource probe, not external E2E."""
import argparse
import json
from pathlib import Path
import resource
import time
import unittest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-cgroup-limits',action='store_true')
    args=parser.parse_args()
    root=Path('/sys/fs/cgroup')
    def read(name):
        try:return (root/name).read_text().strip()
        except OSError:return None
    memory=read('memory.max');cpu=read('cpu.max')
    limited=memory is not None and memory!='max' and int(memory)<=256*1024*1024
    cpu_limited=False
    if cpu and cpu.split()[0]!='max':
        quota,period=map(int,cpu.split());cpu_limited=quota<=period
    if args.require_cgroup_limits and not (limited and cpu_limited):
        raise RuntimeError('PROVIDER_PROBE_REQUIRES_256MIB_ONE_CPU_CGROUP')
    started=time.perf_counter()
    suite=unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromName('tests.test_isolated_execution'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_isolated_delivery_io'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_research_diagnostics'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_integrated_features'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_integrated_launcher'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_provider_bridge'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_provider_identity'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_current_market_review'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_forecast_error_review'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_market_direction_ui'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_analyze_input_guard'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_current_roster'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_current_roster_telegram'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_current_roster_native'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_player_minutes'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_player_inputs'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_player_shadow'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_player_input_batch'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_player_input_launcher'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_roster_diagnostics'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_roster_denver_native'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_official_report_link'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_challenger_review'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_posterior_refresh'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_challenger_forward'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_challenger_summary'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_europe_integration'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_europe_city_alias'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_europe_command_identity'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_pipeline_diagnostics'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_runtime_identity'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_device_verification'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_quality_comparison_summary'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_europe_premium_ui'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_europe_data'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_europe_provider_identity'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_europe_prematch'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_nba_overnight'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_adaptive_research'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_issue90'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_critical_integrity'),
        unittest.defaultTestLoader.loadTestsFromName('tests.test_provider_seasons')])
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report=dict(format='ISOLATED_PROVIDER_RUNTIME_V1',tests=result.testsRun,
                failures=len(result.failures),errors=len(result.errors),elapsed_seconds=time.perf_counter()-started,
                peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                cgroup_memory_max=memory,cgroup_cpu_max=cpu,cgroup_memory_peak=read('memory.peak'),
                cgroup_limits_verified=limited and cpu_limited,
                transport='SYNTHETIC_PROVIDER_RESPONSES_AND_LOCAL_HTTP_TELEGRAM',
                actual_provider_authentication_verified=False,actual_telegram_delivery_verified=False,
                production_changed=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
