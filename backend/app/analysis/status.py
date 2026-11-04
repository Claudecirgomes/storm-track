PENDING_METHODS = {
    "cell_detection": "PENDING_METHOD_AND_VALIDATION",
    "cell_tracking": "PENDING_METHOD_AND_VALIDATION",
    "wind_risk": "PENDING_METHOD_AND_VALIDATION",
    "hail_risk": "PENDING_METHOD_AND_VALIDATION",
    "rotation_assessment": "PENDING_METHOD_AND_VALIDATION",
    "nowcast": "PENDING_METHOD_AND_VALIDATION",
    "stormtrack_alerts": "PENDING_METHOD_AND_VALIDATION",
}


def analysis_status() -> dict:
    return {
        "status": "NOT_OPERATIONAL",
        "methods": dict(PENDING_METHODS),
        "cell_detection": {
            "available": False,
            "status": "WAITING_FOR_SOURCE_AND_METHOD",
            "reason": "É necessária uma fonte quantitativa de radar ou infravermelho, "
                      "um método definido e validação com casos históricos.",
            "requirements": ["Fonte quantitativa georreferenciada", "Método e limiares versionados", "Validação independente"],
        },
        "reason": "Método, limiares, versão e validação com casos históricos ainda não aprovados.",
    }
