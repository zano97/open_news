"""Canonicalizzazione degli URL per il dedup.

Regole deliberatamente conservative: si rimuovono solo frammenti e parametri
di tracciamento noti; il percorso non viene mai alterato.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAM_PREFIXES = ("utm_", "mtm_", "pk_", "piwik_")
TRACKING_PARAMS = frozenset(
    {
        "fbclid", "gclid", "dclid", "msclkid", "twclid", "igshid", "mc_cid",
        "mc_eid", "cmp", "cmpid", "smid", "ocid", "ns_campaign", "ns_mchannel",
        "ns_source", "ns_linkname", "at_medium", "at_campaign", "xtor", "ref_src",
        "wt_mc", "s_kwcid", "spm", "share", "src",
    }
)


def _is_tracking(param: str) -> bool:
    lowered = param.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PARAM_PREFIXES)


def canonicalize(url: str) -> str:
    """URL stabile: host minuscolo, niente frammento, niente parametri di tracking."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port is not None and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not _is_tracking(k)]
    query.sort()
    return urlunsplit((
        parts.scheme.lower() or "https",
        host,
        parts.path or "/",
        urlencode(query),
        "",  # frammento sempre rimosso
    ))
