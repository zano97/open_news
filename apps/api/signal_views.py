"""Dai segnali grezzi (BiasSignal) alle viste per i template.

Solo rimodellamento per la presentazione: nessun nuovo calcolo, nessuna
aggregazione tra livelli. Ogni vista conserva periodo, n e versione del metodo
per il tooltip "Da dove viene questo dato?".
"""

from dataclasses import dataclass, field
from typing import Any

from core.models import BiasSignal


@dataclass
class SignalView:
    signal: BiasSignal
    data: dict[str, Any] = field(default_factory=dict)


def _latest_by_type(signals: list[BiasSignal]) -> dict[str, BiasSignal]:
    latest: dict[str, BiasSignal] = {}
    for signal in sorted(signals, key=lambda s: s.period_end, reverse=True):
        latest.setdefault(signal.signal_type, signal)
    return latest


def shape_signals(
    signals: list[BiasSignal], topic_labels: dict[str, str]
) -> dict[str, SignalView]:
    """Ritorna {tipo: vista} usando il segnale più recente di ciascun tipo."""
    views: dict[str, SignalView] = {}
    latest = _latest_by_type(signals)

    agenda = latest.get("agenda")
    if agenda and isinstance(agenda.value, dict):
        rows = []
        for topic_id, stats in agenda.value.items():
            rows.append(
                {
                    "topic": topic_labels.get(topic_id, topic_id),
                    "deviation_pts": round(stats["deviation"] * 100, 1),
                    "share_pts": round(stats["share"] * 100, 1),
                    "mean_pts": round(stats["mean"] * 100, 1),
                    "ci_low_pts": round(stats["ci_low"] * 100, 1),
                    "ci_high_pts": round(stats["ci_high"] * 100, 1),
                    # Scostamento "solido" se l'intervallo bootstrap non attraversa lo zero.
                    "significant": stats["ci_low"] > 0 or stats["ci_high"] < 0,
                }
            )
        rows.sort(key=lambda r: r["deviation_pts"], reverse=True)
        views["agenda"] = SignalView(
            agenda, {"over": rows[:3], "under": rows[-3:][::-1]}
        )

    tone = latest.get("tone")
    if tone and isinstance(tone.value, dict):
        total = sum(tone.value.values()) or 1
        views["tone"] = SignalView(
            tone,
            {
                "distribution": tone.value,
                "percent": {
                    k: round(v * 100 / total) for k, v in tone.value.items()
                },
            },
        )

    framing = latest.get("framing")
    if framing and isinstance(framing.value, dict):
        groups = framing.value.get("groups", {})
        ranked = sorted(
            (
                (gid, terms, sum(terms.values()))
                for gid, terms in groups.items()
            ),
            key=lambda item: item[2],
            reverse=True,
        )
        views["framing"] = SignalView(
            framing,
            {
                "top_groups": [
                    {
                        "id": gid,
                        "total": total,
                        "terms": sorted(
                            terms.items(), key=lambda kv: kv[1], reverse=True
                        ),
                    }
                    for gid, terms, total in ranked[:4]
                ]
            },
        )

    actors = latest.get("actors")
    if actors and isinstance(actors.value, dict):
        roles = actors.value.get("roles", {})
        total_roles = sum(roles.values()) or 1
        views["actors"] = SignalView(
            actors,
            {
                "roles": sorted(roles.items(), key=lambda kv: kv[1], reverse=True),
                "roles_percent": {
                    k: round(v * 100 / total_roles) for k, v in roles.items()
                },
                "top_speakers": actors.value.get("top_speakers", [])[:5],
            },
        )

    blindspot = latest.get("blindspot")
    if blindspot and isinstance(blindspot.value, dict):
        views["blindspot"] = SignalView(
            blindspot,
            {
                "count": blindspot.value.get("count", 0),
                "story_ids": blindspot.value.get("story_ids", [])[-5:],
                "threshold_pct": round(
                    float(blindspot.value.get("threshold", 0)) * 100
                ),
                "peers": blindspot.value.get("peers", 0),
            },
        )

    cocoverage = latest.get("cocoverage")
    if cocoverage and isinstance(cocoverage.value, dict):
        views["cocoverage"] = SignalView(cocoverage, dict(cocoverage.value))

    # Livello 4: un segnale per asse, il più recente di ciascuno.
    annotation_axes: dict[str, BiasSignal] = {}
    for signal in sorted(signals, key=lambda s: s.period_end, reverse=True):
        if signal.signal_type == "annotation" and signal.axis:
            annotation_axes.setdefault(signal.axis, signal)
    if annotation_axes:
        views["annotation"] = SignalView(
            next(iter(annotation_axes.values())),
            {axis: dict(s.value) for axis, s in annotation_axes.items()
             if isinstance(s.value, dict)},
        )

    return views
