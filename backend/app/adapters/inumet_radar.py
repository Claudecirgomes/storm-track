from backend.app.adapters.pending_source import PendingSourceConnector, SourceProfile


class InumetRadarConnector(PendingSourceConnector):
    profile = SourceProfile("INUMET", "RADAR-UY", "Instituto Uruguayo de Meteorología")
