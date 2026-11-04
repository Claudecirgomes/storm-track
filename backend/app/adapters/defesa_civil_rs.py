from backend.app.adapters.pending_source import PendingSourceConnector, SourceProfile


class DefesaCivilRsConnector(PendingSourceConnector):
    profile = SourceProfile("DEFESA_CIVIL_RS", "ALERTAS-RS", "Defesa Civil do Rio Grande do Sul")
