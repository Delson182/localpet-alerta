from pathlib import Path
import streamlit.components.v1 as components

_FRONTEND = Path(__file__).parent / "frontend"

_component = components.declare_component(
    "localpet_geolocation_button",
    path=str(_FRONTEND),
)


def geolocation_button(
    label="📍 Usar minha localização",
    key=None,
):
    return _component(
        label=label,
        key=key,
        default=None,
    )
