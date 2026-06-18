# API loteria.cl — formato de respuesta

Documentación del endpoint que alimenta el scraper de Kino
(`src/scrapers/scraper_loteria.py`).

## Endpoint

```
GET https://rckino.loteria.cl/api/sorteos          → últimos ~26 sorteos (ventana)
GET https://rckino.loteria.cl/api/sorteos?sorteo=N → sorteo N (solo si está en la ventana)
```

Headers usados por el scraper:

```http
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
Referer: https://rckino.loteria.cl/resultados
Accept: application/json, text/plain, */*
Accept-Language: es-CL,es;q=0.9
```

**Encoding:** la API responde en **ISO-8859-1 (latin-1)**, no UTF-8. Si se decodifica
como UTF-8, las tildes salen rotas (`categor�as`). El scraper actual decodifica con
`errors="replace"`, lo que mancha los textos — no afecta los datos porque solo extrae
dígitos de `bolitas`, pero para leer `descripcion`/`nombreCategoria` hay que decodificar
como `latin-1`.

## Estructura

```
info
├── sorteosDisponibles : [int]      ventana de ~26 sorteos disponibles
├── resumen
│   ├── fechaSorteo        : "DD/MM/YYYY"
│   ├── fechaProximoSorteo : "19 de junio 2026"
│   ├── pozoTotal          : "9.850"   (string, miles con punto)
│   └── numeroSorteo       : int
└── secciones : [ ... ]             una por variante de juego
```

Cada elemento de `secciones`:

| Campo | Tipo | Notas |
|---|---|---|
| `codigoVariante` | int | identifica el juego (ver tabla abajo) |
| `bolitas` | string | `"03,05,06,..."` — 14 números, 2 dígitos con cero a la izquierda, ascendente. Vacío `""` en variantes sin sorteo de bolitas. |
| `descripcion` | string | texto del juego |
| `mensajeGanador` | string | |
| `pozoEstimado` | string | miles con punto |
| `categorias` | array | premios por nº de aciertos |

### Variantes (`codigoVariante`)

| Código | Juego | ¿Va al CSV? |
|---|---|---|
| `0` | **KINO** | ✅ |
| `1` | **ReKino** | ✅ |
| `2` | **RequeteKino** | ✅ |
| `3` | Chao Jefe $2M (sueldo 50 años) | ❌ |
| `4` | Chao Jefe $3M (sueldo 30 años) | ❌ |
| `5` | Súper Marraqueta (casa + SUV + sueldo) | ❌ |
| `98` | Premio Cartón (gana por nº de cartón; `bolitas` vacío) | ❌ |
| `99` | Premio Especial (auto/viaje; las `bolitas` van **dentro de cada `categoria`** con `numeroExtraccion`) | ❌ |
| `-1` | Club Kino (informativo, sin bolitas) | ❌ |

El scraper (`VARIANT_MAP`) solo mapea `0`/`1`/`2`.

### Categorías

Cada `categoria` trae premios como **strings** con `$` y separador de miles `.`:

```json
{
  "codigoCategoria": 1,
  "nombreCategoria": "14 Aciertos",
  "premioTotal": "$5.293.396.883",
  "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null },
  "premioIndividual": "-",
  "clasificacionPremio": "estandar"
}
```

En premios por cartón (`codigoVariante: 98`), `ganadoresPremioMayor` es un array con
`numeroCarton`, `ciudad` y `premio` de cada ganador.

## Ejemplo completo

Sorteo **3241** (17/06/2026). JSON crudo guardado aparte en
[`ejemplo-sorteo-3241.json`](./ejemplo-sorteo-3241.json).

Números sorteados:

- **KINO:** `03,05,06,07,09,11,14,15,16,20,21,22,23,24`
- **ReKino:** `01,05,06,08,10,11,12,13,14,15,18,19,21,22`
- **RequeteKino:** `02,05,09,10,12,13,14,15,16,17,18,19,20,23`

```json
{
  "info": {
    "sorteosDisponibles": [
      3241, 3240, 3239, 3238, 3237, 3236, 3235, 3234, 3233, 3232,
      3231, 3230, 3229, 3228, 3227, 3226, 3225, 3224, 3223, 3222,
      3221, 3220, 3219, 3218, 3217, 3216
    ],
    "resumen": {
      "fechaSorteo": "17/06/2026",
      "fechaProximoSorteo": "19 de junio 2026",
      "pozoTotal": "9.850",
      "numeroSorteo": 3241
    },
    "secciones": [
      {
        "codigoVariante": 0,
        "urlImagen": "/assets/images/kino.svg",
        "descripcion": "Estimado a repartir entre todas las categorías Kino",
        "bolitas": "03,05,06,07,09,11,14,15,16,20,21,22,23,24",
        "mensajeGanador": "No hubo ganadores con 14 Aciertos.",
        "pozoEstimado": "5.520",
        "categorias": [
          { "codigoCategoria": 1, "nombreCategoria": "14 Aciertos", "premioTotal": "$5.293.396.883", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "tipoCalculo": 1, "tipoPremio": 1, "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false },
          { "codigoCategoria": 2, "nombreCategoria": "13 Aciertos", "premioTotal": "$12.280.303", "ganadores": { "cantidad": "19", "ganadoresPremioMayor": null }, "premioIndividual": "$633.405", "tipoCalculo": 1, "tipoPremio": 1, "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false },
          { "codigoCategoria": 3, "nombreCategoria": "12 Aciertos", "premioTotal": "$3.550.000", "ganadores": { "cantidad": "355", "ganadoresPremioMayor": null }, "premioIndividual": "$10.000", "tipoCalculo": 1, "tipoPremio": 1, "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false },
          { "codigoCategoria": 4, "nombreCategoria": "11 Aciertos", "premioTotal": "$17.111.500", "ganadores": { "cantidad": "4.889", "ganadoresPremioMayor": null }, "premioIndividual": "$3.500", "tipoCalculo": 1, "tipoPremio": 1, "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false },
          { "codigoCategoria": 5, "nombreCategoria": "10 Aciertos", "premioTotal": "$27.767.000", "ganadores": { "cantidad": "27.767", "ganadoresPremioMayor": null }, "premioIndividual": "$1.000", "tipoCalculo": 1, "tipoPremio": 1, "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false }
        ]
      },
      {
        "codigoVariante": 99,
        "urlImagen": "/assets/images/pe.svg",
        "descripcion": "",
        "bolitas": "",
        "mensajeGanador": "No hubo ganadores de premios promocionales.",
        "pozoEstimado": "",
        "categorias": [
          { "codigoCategoria": 12, "nombreCategoria": "Mitsubishi L200 o $30.000.000", "premioTotal": "$0", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "clasificacionPremio": "categoria-especial", "esPremioEspecialCategoria": true, "esPremioNumeroCarton": false, "bolitas": "01,02,06,07,10,11,12,13,15,16,17,18,20,22", "numeroExtraccion": 1 },
          { "codigoCategoria": 13, "nombreCategoria": "Viaje para 2 o $10.000.000", "premioTotal": "$0", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "clasificacionPremio": "categoria-especial", "esPremioEspecialCategoria": true, "esPremioNumeroCarton": false, "bolitas": "04,05,06,07,10,11,12,13,16,17,19,22,23,25", "numeroExtraccion": 1 },
          { "codigoCategoria": 13, "nombreCategoria": "Viaje para 2 o $10.000.000", "premioTotal": "$0", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "clasificacionPremio": "categoria-especial", "esPremioEspecialCategoria": true, "esPremioNumeroCarton": false, "bolitas": "04,05,06,09,12,13,14,15,16,17,19,20,24,25", "numeroExtraccion": 2 }
        ]
      },
      {
        "codigoVariante": 1,
        "urlImagen": "/assets/images/rekino.svg",
        "descripcion": "Estimado a repartir entre todas las categorías ReKino",
        "bolitas": "01,05,06,08,10,11,12,13,14,15,18,19,21,22",
        "mensajeGanador": "No hubo ganadores con 14 Aciertos.",
        "pozoEstimado": "690",
        "categorias": [
          { "codigoCategoria": 6, "nombreCategoria": "14 Aciertos", "premioTotal": "$643.210.530", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false }
        ]
      },
      {
        "codigoVariante": 2,
        "urlImagen": "/assets/images/requetekino.svg",
        "descripcion": "Estimado a repartir entre todas las categorías RequeteKino",
        "bolitas": "02,05,09,10,12,13,14,15,16,17,18,19,20,23",
        "mensajeGanador": "No hubo ganadores con 14 Aciertos.",
        "pozoEstimado": "360",
        "categorias": [
          { "codigoCategoria": 7, "nombreCategoria": "14 Aciertos", "premioTotal": "$313.110.730", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false }
        ]
      },
      {
        "codigoVariante": 3,
        "urlImagen": "/assets/images/chaojefe2m.svg",
        "descripcion": "Sueldo de $2.000.000 mensuales, por 50 años, heredable",
        "bolitas": "01,02,05,07,09,13,14,15,16,18,19,20,22,25",
        "mensajeGanador": "No hubo ganadores con 14 Aciertos.",
        "pozoEstimado": "1.200",
        "categorias": [
          { "codigoCategoria": 8, "nombreCategoria": "14 Aciertos", "premioTotal": "$1.224.489.796", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false }
        ]
      },
      {
        "codigoVariante": 4,
        "urlImagen": "/assets/images/chaojefe3m.svg",
        "descripcion": "Sueldo de $3.000.000 mensuales, por 30 años, heredable",
        "bolitas": "02,05,06,07,08,10,12,15,16,17,19,20,21,25",
        "mensajeGanador": "No hubo ganadores con 14 Aciertos.",
        "pozoEstimado": "1.080",
        "categorias": [
          { "codigoCategoria": 9, "nombreCategoria": "14 Aciertos", "premioTotal": "$1.102.040.816", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false }
        ]
      },
      {
        "codigoVariante": 5,
        "urlImagen": "/assets/images/supermarraqueta.png",
        "descripcion": "1 Casa + 1 SUV + Sueldo de $1 Millón por 50 años Heredable + 1 Viaje",
        "bolitas": "03,04,05,06,07,09,13,16,18,19,20,23,24,25",
        "mensajeGanador": "No hubo ganadores con 14 Aciertos.",
        "pozoEstimado": "1.000",
        "categorias": [
          { "codigoCategoria": 10, "nombreCategoria": "14 Aciertos", "premioTotal": "$1.020.408.163", "ganadores": { "cantidad": "0", "ganadoresPremioMayor": null }, "premioIndividual": "-", "clasificacionPremio": "estandar", "esPremioEspecialCategoria": false, "esPremioNumeroCarton": false }
        ]
      },
      {
        "codigoVariante": 98,
        "urlImagen": "/assets/images/pc.svg",
        "descripcion": "1 Casa + 1 SUV + Sueldo de $1.500.000 mensuales, por 30 años, heredable + 1 Viaje",
        "bolitas": "",
        "mensajeGanador": "No hubo ganadores con 14 Aciertos.",
        "pozoEstimado": "",
        "categorias": [
          {
            "codigoCategoria": 11,
            "nombreCategoria": "Bono de $1.000.000",
            "premioTotal": "$5.102.041",
            "ganadores": {
              "cantidad": "5",
              "ganadoresPremioMayor": [
                { "numeroCarton": "YL 140.968", "ciudad": "La Serena",     "premio": "Bono de $1.000.000", "clasificacionPremio": "numero-carton" },
                { "numeroCarton": "YL 262.227", "ciudad": "Internet",      "premio": "Bono de $1.000.000", "clasificacionPremio": "numero-carton" },
                { "numeroCarton": "YL 303.236", "ciudad": "Alto Hospicio", "premio": "Bono de $1.000.000", "clasificacionPremio": "numero-carton" },
                { "numeroCarton": "YL 322.047", "ciudad": "Internet",      "premio": "Bono de $1.000.000", "clasificacionPremio": "numero-carton" },
                { "numeroCarton": "YL 399.193", "ciudad": "Internet",      "premio": "Bono de $1.000.000", "clasificacionPremio": "numero-carton" }
              ]
            },
            "premioIndividual": "$1.000.000",
            "tipoCalculo": 2,
            "tipoPremio": 1,
            "clasificacionPremio": "numero-carton",
            "esPremioEspecialCategoria": false,
            "esPremioNumeroCarton": true
          }
        ]
      },
      {
        "codigoVariante": -1,
        "urlImagen": "/assets/images/ck.svg",
        "descripcion": "Jugando con tu RUT, Tarjeta Club Kino o en www.loteria.cl, siempre acumulas Puntos Club Kino que puedes canjear por Juegos Lotería.",
        "bolitas": "",
        "mensajeGanador": "",
        "pozoEstimado": "",
        "categorias": []
      }
    ]
  }
}
```

---

_Documento generado el 2026-06-18. Ejemplo capturado en vivo desde
`rckino.loteria.cl/api/sorteos?sorteo=3241`. El JSON crudo (con todos los campos
sin recortar) está en `ejemplo-sorteo-3241.json`._
