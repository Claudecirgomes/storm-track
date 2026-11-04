from backend.app.adapters.pending_source import PendingSourceConnector, SourceProfile


class CptecInpeConnector(PendingSourceConnector):
    profile = SourceProfile("CPTEC", "PRODUTO-SATELITE-RADAR", "CPTEC/INPE")
