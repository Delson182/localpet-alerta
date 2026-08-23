from pathlib import Path
from datetime import datetime
import re
import time

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

from geolocalizacao_component import geolocation_button


st.set_page_config(
    page_title="LocalPet Alerta",
    page_icon="🐾",
    layout="wide",
)

# =========================================================
# CONFIGURAÇÕES
# =========================================================

# Centro aproximado do Brasil
LAT_PADRAO = -14.2350
LON_PADRAO = -51.9253
ZOOM_BRASIL = 4

ARQUIVO_DADOS = Path("dados/ocorrencias.csv")

COLUNAS = [
    "id",
    "data_registro",
    "especie",
    "situacao",
    "cep",
    "endereco_informado",
    "endereco_formatado",
    "descricao",
    "latitude",
    "longitude",
    "status",
]

HEADERS_NOMINATIM = {
    "User-Agent": "LocalPetAlerta/1.0 (prototipo educacional)"
}


# =========================================================
# ESTADO
# =========================================================

def inicializar_estado():
    valores = {
        "mapa_centro_lat": LAT_PADRAO,
        "mapa_centro_lon": LON_PADRAO,
        "mapa_zoom": ZOOM_BRASIL,
        "mapa_usuario_ativo": False,

        "cad_centro_lat": LAT_PADRAO,
        "cad_centro_lon": LON_PADRAO,
        "cad_zoom": ZOOM_BRASIL,
        "cad_ponto_lat": None,
        "cad_ponto_lon": None,
        "cad_origem_local": "",
        "cad_sugestao_id": "",
    }

    for chave, valor in valores.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor


inicializar_estado()


# =========================================================
# CSV / PANDAS
# =========================================================

def preparar_arquivo():
    ARQUIVO_DADOS.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not ARQUIVO_DADOS.exists():
        pd.DataFrame(columns=COLUNAS).to_csv(
            ARQUIVO_DADOS,
            index=False,
            encoding="utf-8-sig",
        )


def carregar_dados():
    preparar_arquivo()

    df = pd.read_csv(ARQUIVO_DADOS)

    # Compatibilidade caso exista CSV de versão anterior.
    for coluna in COLUNAS:
        if coluna not in df.columns:
            df[coluna] = ""

    df = df[COLUNAS]

    for coluna in ["latitude", "longitude"]:
        df[coluna] = pd.to_numeric(
            df[coluna],
            errors="coerce",
        )

    return df


def salvar_dados(df):
    df.to_csv(
        ARQUIVO_DADOS,
        index=False,
        encoding="utf-8-sig",
    )


def proximo_id(df):
    if df.empty:
        return 1

    ids = pd.to_numeric(
        df["id"],
        errors="coerce",
    ).dropna()

    if ids.empty:
        return 1

    return int(ids.max()) + 1


# =========================================================
# CEP
# =========================================================

def limpar_cep(cep):
    return re.sub(r"\D", "", cep or "")


@st.cache_data(show_spinner=False, ttl=3600)
def consultar_cep(cep):
    cep_limpo = limpar_cep(cep)

    if len(cep_limpo) != 8:
        raise ValueError(
            "Informe um CEP válido com 8 dígitos."
        )

    resposta = requests.get(
        f"https://viacep.com.br/ws/{cep_limpo}/json/",
        timeout=15,
    )
    resposta.raise_for_status()

    dados = resposta.json()

    if dados.get("erro"):
        raise ValueError("CEP não encontrado.")

    partes = [
        dados.get("logradouro", ""),
        dados.get("bairro", ""),
        dados.get("localidade", ""),
        dados.get("uf", ""),
        cep_limpo,
        "Brasil",
    ]

    endereco_busca = ", ".join(
        parte for parte in partes if parte
    )

    return {
        "cep": cep_limpo,
        "logradouro": dados.get("logradouro", ""),
        "bairro": dados.get("bairro", ""),
        "cidade": dados.get("localidade", ""),
        "uf": dados.get("uf", ""),
        "endereco_busca": endereco_busca,
    }


# =========================================================
# NOMINATIM / OPENSTREETMAP
# =========================================================

@st.cache_data(show_spinner=False, ttl=1800)
def buscar_sugestoes_endereco(texto):
    texto = (texto or "").strip()

    if len(texto) < 4:
        return []

    url = "https://nominatim.openstreetmap.org/search"

    params = {
        "q": texto,
        "format": "jsonv2",
        "limit": 6,
        "addressdetails": 1,
        "countrycodes": "br",
    }

    resposta = requests.get(
        url,
        params=params,
        headers=HEADERS_NOMINATIM,
        timeout=20,
    )
    resposta.raise_for_status()

    resultados = resposta.json()
    time.sleep(1)

    sugestoes = []

    for item in resultados:
        sugestoes.append(
            {
                "id": str(item.get("place_id", "")),
                "nome": item.get("display_name", ""),
                "latitude": float(item["lat"]),
                "longitude": float(item["lon"]),
            }
        )

    return sugestoes


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar(endereco):
    url = "https://nominatim.openstreetmap.org/search"

    params = {
        "q": endereco,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
        "countrycodes": "br",
    }

    resposta = requests.get(
        url,
        params=params,
        headers=HEADERS_NOMINATIM,
        timeout=20,
    )
    resposta.raise_for_status()

    resultados = resposta.json()

    if not resultados:
        raise ValueError(
            "Não foi possível localizar esse endereço."
        )

    item = resultados[0]
    time.sleep(1)

    return {
        "latitude": float(item["lat"]),
        "longitude": float(item["lon"]),
        "endereco_formatado": item.get(
            "display_name",
            endereco,
        ),
    }


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar_reverso(latitude, longitude):
    url = "https://nominatim.openstreetmap.org/reverse"

    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "jsonv2",
        "addressdetails": 1,
        "zoom": 18,
    }

    resposta = requests.get(
        url,
        params=params,
        headers=HEADERS_NOMINATIM,
        timeout=20,
    )
    resposta.raise_for_status()

    dados = resposta.json()
    time.sleep(1)

    return dados.get(
        "display_name",
        f"{latitude:.6f}, {longitude:.6f}",
    )


# =========================================================
# GPS
# =========================================================

def interpretar_gps(resultado):
    """
    Retorna:
    latitude, longitude, precisao_metros, erro
    """

    if not resultado:
        return None, None, None, None

    if isinstance(resultado, dict) and resultado.get("error"):
        erro = resultado["error"]
        codigo = erro.get("code")

        if codigo == 1:
            return (
                None,
                None,
                None,
                "Permissão de localização negada pelo navegador.",
            )

        return (
            None,
            None,
            None,
            erro.get(
                "message",
                "Não foi possível obter a localização.",
            ),
        )

    if not isinstance(resultado, dict):
        return None, None, None, None

    lat = resultado.get("latitude")
    lon = resultado.get("longitude")
    accuracy = resultado.get("accuracy")

    if lat is None or lon is None:
        return None, None, None, None

    return (
        float(lat),
        float(lon),
        float(accuracy) if accuracy is not None else None,
        None,
    )


def mensagem_precisao_gps(accuracy):
    if accuracy is None:
        st.warning(
            "O navegador não informou a precisão. "
            "Confirme o ponto no mapa."
        )
        return True

    if accuracy <= 100:
        st.success(
            f"📍 Boa precisão: aproximadamente {accuracy:.0f} m."
        )
        return True

    if accuracy <= 1000:
        st.warning(
            f"📍 Localização aproximada: cerca de {accuracy:.0f} m. "
            "Confirme ou ajuste o ponto no mapa."
        )
        return True

    if accuracy <= 5000:
        st.warning(
            f"⚠️ Localização pouco precisa: cerca de "
            f"{accuracy / 1000:.1f} km. "
            "Recomenda-se ajustar manualmente no mapa."
        )
        return True

    st.error(
        f"⚠️ A localização fornecida pelo navegador está muito "
        f"imprecisa ({accuracy / 1000:.1f} km). "
        "Use CEP, endereço ou marque o ponto no mapa."
    )

    # Localização muito ruim não será aceita automaticamente.
    return False


# =========================================================
# MAPAS
# =========================================================

def cor_marcador(situacao, status):
    if status in ["Resgatado", "Reencontrado"]:
        return "green"

    return {
        "Possível abandono": "red",
        "Animal perdido": "blue",
        "Animal de rua": "orange",
        "Não identificado": "gray",
    }.get(situacao, "cadetblue")


def criar_mapa_principal(
    df,
    centro_lat,
    centro_lon,
    zoom_inicial,
    mostrar_usuario=False,
):
    pontos = df.dropna(
        subset=["latitude", "longitude"]
    ).copy()

    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=zoom_inicial,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    if mostrar_usuario:
        folium.CircleMarker(
            [centro_lat, centro_lon],
            radius=8,
            color="#1976d2",
            fill=True,
            fill_color="#1976d2",
            fill_opacity=0.9,
            tooltip="Sua localização aproximada",
            popup="Sua localização aproximada",
        ).add_to(mapa)

    for _, linha in pontos.iterrows():
        popup = folium.Popup(
            f"""
            <b>{linha.get("especie", "")}</b><br>
            <b>Situação:</b> {linha.get("situacao", "")}<br>
            <b>Status:</b> {linha.get("status", "")}<br>
            <b>Local:</b> {linha.get("endereco_formatado", "")}<br>
            <b>Descrição:</b> {linha.get("descricao", "")}
            """,
            max_width=350,
        )

        folium.Marker(
            location=[
                float(linha["latitude"]),
                float(linha["longitude"]),
            ],
            popup=popup,
            tooltip=(
                f'{linha.get("especie", "")} - '
                f'{linha.get("situacao", "")}'
            ),
            icon=folium.Icon(
                color=cor_marcador(
                    linha.get("situacao", ""),
                    linha.get("status", ""),
                ),
                icon="paw",
                prefix="fa",
            ),
        ).add_to(mapa)

    return mapa


def criar_mapa_cadastro(
    df,
    centro_lat,
    centro_lon,
    zoom_inicial,
    ponto_lat=None,
    ponto_lon=None,
):
    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=zoom_inicial,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    # Mira fixa no centro do mapa.
    # Útil principalmente no celular: mova o mapa e confirme
    # o ponto usando o botão abaixo dele.
    mira_html = """
    <div style="
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        z-index: 9999;
        pointer-events: none;
        font-size: 36px;
        line-height: 36px;
        color: #d32f2f;
        font-weight: 700;
        text-shadow:
            -1px -1px 0 #ffffff,
             1px -1px 0 #ffffff,
            -1px  1px 0 #ffffff,
             1px  1px 0 #ffffff;
    ">⊕</div>
    """

    mapa.get_root().html.add_child(
        folium.Element(mira_html)
    )

    # Mostra também todas as ocorrências já cadastradas.
    pontos_salvos = df.dropna(
        subset=["latitude", "longitude"]
    ).copy()

    for _, linha in pontos_salvos.iterrows():
        popup = folium.Popup(
            f"""
            <b>Ocorrência #{linha.get("id", "")}</b><br>
            <b>Espécie:</b> {linha.get("especie", "")}<br>
            <b>Situação:</b> {linha.get("situacao", "")}<br>
            <b>Status:</b> {linha.get("status", "")}<br>
            <b>Local:</b> {linha.get("endereco_formatado", "")}<br>
            <b>Descrição:</b> {linha.get("descricao", "")}
            """,
            max_width=350,
        )

        folium.Marker(
            location=[
                float(linha["latitude"]),
                float(linha["longitude"]),
            ],
            popup=popup,
            tooltip=(
                f'#{linha.get("id", "")} - '
                f'{linha.get("especie", "")} - '
                f'{linha.get("status", "")}'
            ),
            icon=folium.Icon(
                color=cor_marcador(
                    linha.get("situacao", ""),
                    linha.get("status", ""),
                ),
                icon="paw",
                prefix="fa",
            ),
        ).add_to(mapa)

    # O ponto que está sendo escolhido para o novo cadastro
    # aparece com um marcador diferente dos já salvos.
    if ponto_lat is not None and ponto_lon is not None:
        folium.Marker(
            [ponto_lat, ponto_lon],
            tooltip="Novo ponto selecionado",
            popup="Local selecionado para a nova ocorrência",
            icon=folium.Icon(
                color="purple",
                icon="map-marker",
            ),
        ).add_to(mapa)

    return mapa


def definir_ponto_cadastro(
    lat,
    lon,
    origem="",
    zoom=16,
):
    st.session_state["cad_ponto_lat"] = float(lat)
    st.session_state["cad_ponto_lon"] = float(lon)
    st.session_state["cad_centro_lat"] = float(lat)
    st.session_state["cad_centro_lon"] = float(lon)
    st.session_state["cad_zoom"] = zoom
    st.session_state["cad_origem_local"] = origem


def atualizar_ponto_por_clique(retorno):
    if not retorno:
        return False

    clique = retorno.get("last_clicked")

    if not clique:
        return False

    lat = float(clique["lat"])
    lon = float(clique["lng"])

    lat_anterior = st.session_state.get("cad_ponto_lat")
    lon_anterior = st.session_state.get("cad_ponto_lon")

    if lat == lat_anterior and lon == lon_anterior:
        return False

    definir_ponto_cadastro(
        lat,
        lon,
        origem="Ponto marcado manualmente no mapa",
        zoom=16,
    )

    return True


def limpar_local_cadastro():
    st.session_state["cad_centro_lat"] = LAT_PADRAO
    st.session_state["cad_centro_lon"] = LON_PADRAO
    st.session_state["cad_zoom"] = ZOOM_BRASIL
    st.session_state["cad_ponto_lat"] = None
    st.session_state["cad_ponto_lon"] = None
    st.session_state["cad_origem_local"] = ""
    st.session_state["cad_sugestao_id"] = ""


# =========================================================
# INTERFACE
# =========================================================

df = carregar_dados()

st.title("🐾 LocalPet Alerta")

st.caption(
    "Protótipo para registro e mapeamento de ocorrências "
    "de animais abandonados ou perdidos."
)



aba_mapa, aba_cadastro, aba_dados = st.tabs(
    [
        "🗺️ Mapa",
        "➕ Registrar ocorrência",
        "📊 Registros",
    ]
)


# =========================================================
# ABA MAPA
# =========================================================

with aba_mapa:
    st.subheader("Mapa de ocorrências")

    filtro1, filtro2 = st.columns(2)

    especies = ["Todas"] + sorted(
        df["especie"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    situacoes = ["Todas"] + sorted(
        df["situacao"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    with filtro1:
        especie_filtro = st.selectbox(
            "Filtrar por espécie",
            especies,
            key="filtro_especie",
        )

    with filtro2:
        situacao_filtro = st.selectbox(
            "Filtrar por situação",
            situacoes,
            key="filtro_situacao",
        )

    st.markdown("##### Localizar região")

    col_cep, col_buscar, col_brasil = st.columns(
        [3, 1, 1]
    )

    with col_cep:
        cep_mapa = st.text_input(
            "CEP",
            placeholder="Ex.: 79210-000",
            key="mapa_cep",
        )

    with col_buscar:
        st.write("")
        st.write("")

        buscar_cep_mapa = st.button(
            "🔎 Buscar CEP",
            use_container_width=True,
            key="btn_buscar_cep_mapa",
        )

    with col_brasil:
        st.write("")
        st.write("")

        voltar_brasil = st.button(
            "🌎 Ver Brasil",
            use_container_width=True,
            key="btn_ver_brasil",
        )

    if buscar_cep_mapa:
        try:
            with st.spinner("Localizando CEP..."):
                dados_cep = consultar_cep(
                    cep_mapa
                )

                geo = geocodificar(
                    dados_cep["endereco_busca"]
                )

            st.session_state["mapa_centro_lat"] = geo[
                "latitude"
            ]

            st.session_state["mapa_centro_lon"] = geo[
                "longitude"
            ]

            st.session_state["mapa_zoom"] = 14
            st.session_state["mapa_usuario_ativo"] = False

            st.success(
                f'📍 {dados_cep["cidade"]} - '
                f'{dados_cep["uf"]}'
            )

            st.rerun()

        except (
            ValueError,
            requests.RequestException,
        ) as erro:
            st.error(str(erro))

    if voltar_brasil:
        st.session_state["mapa_centro_lat"] = LAT_PADRAO
        st.session_state["mapa_centro_lon"] = LON_PADRAO
        st.session_state["mapa_zoom"] = ZOOM_BRASIL
        st.session_state["mapa_usuario_ativo"] = False
        st.rerun()

    mapa_df = df.copy()

    if especie_filtro != "Todas":
        mapa_df = mapa_df[
            mapa_df["especie"] == especie_filtro
        ]

    if situacao_filtro != "Todas":
        mapa_df = mapa_df[
            mapa_df["situacao"] == situacao_filtro
        ]

    gps_texto, gps_controle = st.columns(
        [4, 1]
    )

    with gps_texto:
        if st.session_state["mapa_usuario_ativo"]:
            st.caption(
                "📍 Visualização centrada na localização "
                "fornecida pelo navegador."
            )
        else:
            st.caption(
                "🌎 Visualização inicial: Brasil."
            )

    with gps_controle:
        resultado_gps_mapa = geolocation_button(
            label="📍 Usar minha localização",
            key="gps_mapa",
        )

    (
        gps_lat,
        gps_lon,
        gps_accuracy,
        gps_erro,
    ) = interpretar_gps(resultado_gps_mapa)

    if gps_erro:
        st.warning(gps_erro)

    if gps_lat is not None:
        aceitar_gps = mensagem_precisao_gps(
            gps_accuracy
        )

        if aceitar_gps:
            st.session_state["mapa_centro_lat"] = gps_lat
            st.session_state["mapa_centro_lon"] = gps_lon
            st.session_state["mapa_zoom"] = 16
            st.session_state["mapa_usuario_ativo"] = True

    mapa_principal = criar_mapa_principal(
        mapa_df,
        centro_lat=st.session_state[
            "mapa_centro_lat"
        ],
        centro_lon=st.session_state[
            "mapa_centro_lon"
        ],
        zoom_inicial=st.session_state[
            "mapa_zoom"
        ],
        mostrar_usuario=st.session_state[
            "mapa_usuario_ativo"
        ],
    )

    st_folium(
        mapa_principal,
        width=None,
        height=550,
        returned_objects=[],
        key="mapa_principal",
    )

    st.caption("© OpenStreetMap contributors")


# =========================================================
# ABA CADASTRO
# =========================================================

with aba_cadastro:
    st.subheader(
        "Registrar nova ocorrência"
    )

    c1, c2 = st.columns(2)

    with c1:
        especie = st.selectbox(
            "Espécie",
            [
                "Cachorro",
                "Gato",
                "Outro",
            ],
            key="cad_especie",
        )

        situacao = st.selectbox(
            "Situação",
            [
                "Possível abandono",
                "Animal perdido",
                "Animal de rua",
                "Não identificado",
            ],
            key="cad_situacao",
        )

    with c2:
        status = st.selectbox(
            "Status",
            [
                "Em aberto",
                "Em acompanhamento",
                "Resgatado",
                "Reencontrado",
            ],
            key="cad_status",
        )

    descricao = st.text_area(
        "Descrição",
        placeholder=(
            "Ex.: cachorro caramelo, porte médio, "
            "aparentemente magro, visto próximo à praça..."
        ),
        height=110,
        key="cad_descricao",
    )

    st.markdown("#### Local da ocorrência")

    st.caption(
        "Use CEP, endereço, localização atual ou clique "
        "diretamente no mapa."
    )

    # -----------------------------------------------------
    # CEP NO CADASTRO
    # -----------------------------------------------------

    cep_col, cep_btn = st.columns(
        [4, 1]
    )

    with cep_col:
        cep_cadastro = st.text_input(
            "CEP (opcional)",
            placeholder="Ex.: 79210-000",
            key="cad_cep",
        )

    with cep_btn:
        st.write("")
        st.write("")

        buscar_cep_cadastro = st.button(
            "🔎 Buscar CEP",
            use_container_width=True,
            key="btn_buscar_cep_cadastro",
        )

    if buscar_cep_cadastro:
        try:
            with st.spinner("Localizando CEP..."):
                dados_cep = consultar_cep(
                    cep_cadastro
                )

                geo_cep = geocodificar(
                    dados_cep["endereco_busca"]
                )

            endereco_cep = ", ".join(
                parte
                for parte in [
                    dados_cep["logradouro"],
                    dados_cep["bairro"],
                    (
                        f'{dados_cep["cidade"]} - '
                        f'{dados_cep["uf"]}'
                    ),
                ]
                if parte
            )

            st.session_state[
                "cad_endereco_texto"
            ] = endereco_cep

            definir_ponto_cadastro(
                geo_cep["latitude"],
                geo_cep["longitude"],
                origem=f'CEP {dados_cep["cep"]}',
                zoom=16,
            )

            st.success(
                "CEP localizado. Ajuste o ponto no mapa "
                "se necessário."
            )

            st.rerun()

        except (
            ValueError,
            requests.RequestException,
        ) as erro:
            st.error(str(erro))

    # -----------------------------------------------------
    # ENDEREÇO + SUGESTÕES
    # -----------------------------------------------------

    endereco_texto = st.text_input(
        "Endereço, bairro ou ponto de referência",
        value=st.session_state.get(
            "cad_endereco_texto",
            "",
        ),
        placeholder=(
            "Ex.: Avenida Manoel Murtinho, Anastácio - MS"
        ),
        key="cad_endereco_busca",
    )

    sugestoes = []

    if len(
        (endereco_texto or "").strip()
    ) >= 4:
        try:
            with st.spinner(
                "Buscando sugestões..."
            ):
                sugestoes = buscar_sugestoes_endereco(
                    endereco_texto
                )

        except requests.RequestException:
            sugestoes = []

    if sugestoes:
        opcoes = {
            "Selecione uma sugestão...": None
        }

        for item in sugestoes:
            opcoes[item["nome"]] = item

        sugestao_nome = st.selectbox(
            "Sugestões de locais",
            list(opcoes.keys()),
            key="cad_lista_sugestoes",
        )

        sugestao = opcoes[
            sugestao_nome
        ]

        if sugestao is not None:
            identificador = sugestao["id"]

            if (
                st.session_state[
                    "cad_sugestao_id"
                ]
                != identificador
            ):
                st.session_state[
                    "cad_sugestao_id"
                ] = identificador

                definir_ponto_cadastro(
                    sugestao["latitude"],
                    sugestao["longitude"],
                    origem=sugestao["nome"],
                    zoom=16,
                )

                st.rerun()

    # -----------------------------------------------------
    # GPS NO CADASTRO
    # -----------------------------------------------------

    gps_info, gps_btn = st.columns(
        [4, 1]
    )

    with gps_info:
        st.caption(
            "Ou use a localização fornecida pelo navegador."
        )

    with gps_btn:
        resultado_gps_cadastro = geolocation_button(
            label="📍 Usar minha localização",
            key="gps_cadastro",
        )

    (
        cad_gps_lat,
        cad_gps_lon,
        cad_gps_accuracy,
        cad_gps_erro,
    ) = interpretar_gps(
        resultado_gps_cadastro
    )

    if cad_gps_erro:
        st.warning(cad_gps_erro)

    if cad_gps_lat is not None:
        aceitar_gps = mensagem_precisao_gps(
            cad_gps_accuracy
        )

        if aceitar_gps:
            definir_ponto_cadastro(
                cad_gps_lat,
                cad_gps_lon,
                origem="Localização do navegador",
                zoom=16,
            )

    # -----------------------------------------------------
    # MAPA SEMPRE VISÍVEL NO CADASTRO
    # -----------------------------------------------------

    st.markdown(
        "##### Ajuste o ponto no mapa"
    )

    st.caption(
        "As ocorrências já cadastradas aparecem no mapa. "
        "No computador, clique no local desejado. "
        "No celular, mova o mapa até posicionar a mira vermelha "
        "sobre o local da ocorrência."
    )

    mapa_cadastro = criar_mapa_cadastro(
        df=df,
        centro_lat=st.session_state[
            "cad_centro_lat"
        ],
        centro_lon=st.session_state[
            "cad_centro_lon"
        ],
        zoom_inicial=st.session_state[
            "cad_zoom"
        ],
        ponto_lat=st.session_state[
            "cad_ponto_lat"
        ],
        ponto_lon=st.session_state[
            "cad_ponto_lon"
        ],
    )

    retorno_cadastro = st_folium(
        mapa_cadastro,
        width=None,
        height=470,
        returned_objects=[
            "last_clicked",
            "center",
            "zoom",
        ],
        key="mapa_cadastro",
    )

    # Mantém no estado a última posição visual do mapa.
    # Isso é importante no celular, pois o usuário normalmente
    # arrasta o mapa em vez de clicar em um ponto.
    centro_mapa = retorno_cadastro.get("center")
    zoom_mapa = retorno_cadastro.get("zoom")

    if centro_mapa:
        st.session_state["cad_centro_lat"] = float(
            centro_mapa["lat"]
        )
        st.session_state["cad_centro_lon"] = float(
            centro_mapa["lng"]
        )

    if zoom_mapa is not None:
        st.session_state["cad_zoom"] = int(
            zoom_mapa
        )

    # No computador, o clique direto continua funcionando.
    if atualizar_ponto_por_clique(
        retorno_cadastro
    ):
        st.rerun()

    st.caption(
        "📱 No celular: arraste o mapa até deixar a mira vermelha "
        "exatamente sobre o local e toque no botão abaixo."
    )

    if st.button(
        "📍 Marcar local da mira",
        use_container_width=True,
        key="btn_marcar_centro",
    ):
        definir_ponto_cadastro(
            st.session_state["cad_centro_lat"],
            st.session_state["cad_centro_lon"],
            origem="Ponto confirmado pela mira do mapa",
            zoom=st.session_state["cad_zoom"],
        )

        st.rerun()

    ponto_lat = st.session_state[
        "cad_ponto_lat"
    ]

    ponto_lon = st.session_state[
        "cad_ponto_lon"
    ]

    if (
        ponto_lat is not None
        and ponto_lon is not None
    ):
        st.success(
            f"📌 Local selecionado: "
            f"{ponto_lat:.6f}, "
            f"{ponto_lon:.6f}"
        )

        origem = st.session_state.get(
            "cad_origem_local",
            "",
        )

        if origem:
            st.caption(
                f"Origem da localização: {origem}"
            )

    else:
        st.info(
            "Nenhum ponto definido. "
            "Use CEP, endereço, GPS, clique no mapa no computador "
            "ou posicione a mira e confirme no celular."
        )

    # -----------------------------------------------------
    # ATUALIZAR OCORRÊNCIA EXISTENTE
    # -----------------------------------------------------

    st.divider()
    st.subheader("Atualizar ocorrência existente")

    ocorrencias_ativas = df[
        df["status"].isin(
            ["Em aberto", "Em acompanhamento"]
        )
    ].copy()

    if ocorrencias_ativas.empty:
        st.info(
            "Não há ocorrências em aberto ou em acompanhamento para atualizar."
        )
    else:
        opcoes_ocorrencia = {}

        for _, linha in ocorrencias_ativas.sort_values(
            "id",
            ascending=False,
        ).iterrows():
            id_ocorrencia = int(linha["id"])

            rotulo = (
                f'#{id_ocorrencia} - '
                f'{linha.get("especie", "")} - '
                f'{linha.get("situacao", "")} - '
                f'{linha.get("status", "")}'
            )

            opcoes_ocorrencia[rotulo] = id_ocorrencia

        col_ocorrencia, col_status = st.columns([3, 2])

        with col_ocorrencia:
            ocorrencia_selecionada = st.selectbox(
                "Ocorrência já cadastrada",
                list(opcoes_ocorrencia.keys()),
                key="cad_editar_ocorrencia",
            )

        id_selecionado = opcoes_ocorrencia[
            ocorrencia_selecionada
        ]

        linha_selecionada = df[
            df["id"] == id_selecionado
        ].iloc[0]

        status_atual = str(
            linha_selecionada["status"]
        )

        status_disponiveis = [
            "Em aberto",
            "Em acompanhamento",
            "Resgatado",
            "Reencontrado",
            "Encerrado",
        ]

        try:
            indice_status = status_disponiveis.index(
                status_atual
            )
        except ValueError:
            indice_status = 0

        with col_status:
            novo_status = st.selectbox(
                "Novo status",
                status_disponiveis,
                index=indice_status,
                key="cad_novo_status_existente",
            )

        st.caption(
            f'📍 {linha_selecionada.get("endereco_formatado", "")}'
        )

        descricao_existente = str(
            linha_selecionada.get("descricao", "")
        ).strip()

        if descricao_existente:
            st.caption(
                f"Descrição: {descricao_existente}"
            )

        atualizar_status = st.button(
            "✅ Atualizar status da ocorrência",
            use_container_width=True,
            key="btn_cad_atualizar_status",
        )

        if atualizar_status:
            if novo_status == status_atual:
                st.info(
                    "A ocorrência já possui esse status."
                )
            else:
                df.loc[
                    df["id"] == id_selecionado,
                    "status",
                ] = novo_status

                salvar_dados(df)

                st.success(
                    f"Ocorrência #{id_selecionado} atualizada de "
                    f"“{status_atual}” para “{novo_status}”."
                )

                st.rerun()

    # -----------------------------------------------------
    # SALVAR NOVA OCORRÊNCIA
    # -----------------------------------------------------

    st.divider()

    registrar = st.button(
        "🐾 Registrar ocorrência",
        type="primary",
        use_container_width=True,
        key="btn_registrar",
    )

    if registrar:
        try:
            if not descricao.strip():
                raise ValueError(
                    "Informe uma descrição da ocorrência."
                )

            if (
                ponto_lat is None
                or ponto_lon is None
            ):
                raise ValueError(
                    "Defina o local da ocorrência antes de registrar."
                )

            with st.spinner(
                "Identificando endereço do ponto..."
            ):
                endereco_formatado = geocodificar_reverso(
                    ponto_lat,
                    ponto_lon,
                )

            cep_final = limpar_cep(
                st.session_state.get(
                    "cad_cep",
                    "",
                )
            )

            endereco_informado = (
                endereco_texto.strip()
                or st.session_state.get(
                    "cad_origem_local",
                    "",
                )
                or "Ponto selecionado no mapa"
            )

            novo = {
                "id": proximo_id(df),
                "data_registro": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "especie": especie,
                "situacao": situacao,
                "cep": cep_final,
                "endereco_informado": endereco_informado,
                "endereco_formatado": endereco_formatado,
                "descricao": descricao.strip(),
                "latitude": ponto_lat,
                "longitude": ponto_lon,
                "status": status,
            }

            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        [novo]
                    ),
                ],
                ignore_index=True,
            )

            salvar_dados(df)

            st.success(
                "✅ Ocorrência registrada com sucesso."
            )

            st.write(
                f"📍 **Local:** "
                f"{endereco_formatado}"
            )

            st.write(
                f"**Coordenadas:** "
                f"{ponto_lat:.6f}, "
                f"{ponto_lon:.6f}"
            )

            limpar_local_cadastro()

        except ValueError as erro:
            st.error(str(erro))

        except requests.RequestException as erro:
            st.error(
                f"Erro no serviço de localização: {erro}"
            )

        except Exception as erro:
            st.error(
                f"Não foi possível registrar: {erro}"
            )


# =========================================================
# ABA REGISTROS
# =========================================================

with aba_dados:
    st.subheader(
        "Resumo dos registros"
    )

    m1, m2, m3 = st.columns(3)

    m1.metric(
        "Ocorrências",
        len(df),
    )

    m2.metric(
        "Em aberto",
        int(
            (
                df["status"]
                == "Em aberto"
            ).sum()
        )
        if not df.empty
        else 0,
    )

    m3.metric(
        "Resolvidas",
        int(
            df["status"]
            .isin(
                [
                    "Resgatado",
                    "Reencontrado",
                    "Encerrado",
                ]
            )
            .sum()
        )
        if not df.empty
        else 0,
    )

    if df.empty:
        st.info(
            "Nenhuma ocorrência cadastrada."
        )

    else:
        st.dataframe(
            df[
                [
                    "id",
                    "data_registro",
                    "especie",
                    "situacao",
                    "cep",
                    "endereco_formatado",
                    "status",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

        st.subheader(
            "Ocorrências por espécie"
        )

        contagem = (
            df.groupby(
                "especie"
            )
            .size()
            .reset_index(
                name="quantidade"
            )
            .sort_values(
                "quantidade",
                ascending=False,
            )
        )

        st.bar_chart(
            contagem,
            x="especie",
            y="quantidade",
        )
