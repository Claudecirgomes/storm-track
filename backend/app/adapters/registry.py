"""Inventory of connector code and activation state for the reviewed MVP sources."""

from backend.app.adapters.cptec_inpe import CptecInpeConnector
from backend.app.adapters.defesa_civil_rs import DefesaCivilRsConnector
from backend.app.adapters.inumet_radar import InumetRadarConnector
from backend.app.adapters.noaa_goes19_abi import viewer_metadata
from backend.app.adapters.simepar_radar import SimeparRadarConnector
from backend.app.adapters.smn_sinarame import SmnSinarameConnector


PENDING_CONNECTORS = (
    SimeparRadarConnector(),
    SmnSinarameConnector(),
    InumetRadarConnector(),
    DefesaCivilRsConnector(),
    CptecInpeConnector(),
)


def connector_catalog() -> list[dict]:
    rows = [{
        "provider_code": connector.profile.provider_code,
        "product_code": connector.profile.product_code,
        "source_name": connector.profile.source_name,
        "connector_type": "isolated_fail_closed_scaffold",
        "status": "SOURCE_PROFILE_REQUIRED",
        "enabled": False,
        "required_profile": list(connector.profile.required_profile),
    } for connector in PENDING_CONNECTORS]
    abi = viewer_metadata()
    rows.insert(0, {
        "provider_code": abi["provider_code"],
        "product_code": abi["product_code"],
        "source_name": abi["satellite"],
        "connector_type": "bounded_direct_image_proxy",
        "status": "DIRECT_IN_APP_IMAGES_ACTIVE_NO_ARCHIVE",
        "enabled": True,
        "required_profile": [
            "image_archive_and_processing_require_separate_source_profile",
        ],
    })
    rows.insert(1, {
        "provider_code": "NOAA",
        "product_code": "GLM-L2-LCFA",
        "source_name": "GOES-19 GLM",
        "connector_type": "bounded_object_store_adapter",
        "status": "ADAPTER_IMPLEMENTED_NOT_CONNECTED",
        "enabled": False,
        "required_profile": ["runtime_environment", "netcdf_fixture_validation", "collection_gates"],
    })
    return rows
