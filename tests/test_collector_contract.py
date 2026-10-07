from techtrend.signal.data_collectors.base import SourceCollector


def test_collector_protocol_rejects_missing_interface():
    assert not isinstance(object(), SourceCollector)
    class Collector:
        source_name = "test"
        async def collect(self, cfg, http_settings, source_cfg):
            return []
    assert isinstance(Collector(), SourceCollector)
