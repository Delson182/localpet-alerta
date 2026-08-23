# LocalPet Alerta

Protótipo em Python/Streamlit para registrar e mapear
ocorrências de animais abandonados ou perdidos.

## Recursos

- mapa inicial mostrando o Brasil;
- OpenStreetMap + Folium;
- Pandas + CSV;
- busca por CEP com ViaCEP;
- localização por endereço com Nominatim;
- sugestões de endereço;
- localização pelo navegador;
- verificação da precisão do GPS;
- marcação manual clicando no mapa;
- mapa também disponível durante o cadastro;
- filtros e indicadores básicos.

## Instalação

No terminal:

```bash
pip install -r requirements.txt
```

Depois:

```bash
streamlit run app.py
```

Não é necessária chave de API.

## Observação sobre GPS

Em notebooks e computadores sem GPS físico, a localização
do navegador pode ser aproximada. Por isso o sistema verifica
a precisão informada pelo navegador e permite corrigir o ponto
manualmente, por CEP ou endereço.
