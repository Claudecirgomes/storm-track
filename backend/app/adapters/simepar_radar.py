from backend.app.adapters.pending_source import PendingSourceConnector, SourceProfile


class SimeparRadarConnector(PendingSourceConnector):
    profile = SourceProfile("SIMEPAR", "RADAR-PR", "SIMEPAR")
