from backend.app.adapters.pending_source import PendingSourceConnector, SourceProfile


class SmnSinarameConnector(PendingSourceConnector):
    profile = SourceProfile("SMN", "SINARAME-RADAR", "Servicio Meteorológico Nacional Argentina")
