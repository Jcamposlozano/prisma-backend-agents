"""
Replay de la "Prueba entrevista Maia 01" (PDF) contra el runtime nuevo.

Envía las mismas respuestas del estudiante en el mismo orden y simula el
tracking de estado del frontend:
  - advance_to_next_question -> current_question += 1, turns = 0
  - is_final_summary         -> fin de la entrevista
  - si no                    -> turns += 1

Guarda el transcript completo en _sim_transcript.json. Temporal — borrar.
"""

import json

import httpx

URL = "http://127.0.0.1:8000/api/agents/maia/chat"

# Respuestas del estudiante, transcritas del PDF (condensadas sin perder
# la sustancia argumentativa).
RESPUESTAS = [
    # A1 — problema y alternativas
    "El problema central de Mariola es que ha tocado el 'techo de cristal' de la plataforma, "
    "sufriendo los efectos secundarios del modelo de agregación de Etsy. Aristas críticas: "
    "(1) Estancamiento e hipercompetencia: su tienda tuvo un crecimiento meteórico, pero las ventas "
    "se han estancado; compite contra miles de vendedores y millones de artículos similares. "
    "(2) Dilución de marca: cada vez le cuesta más diferenciarse; los clientes hablan en redes de lo "
    "que compraron 'en Etsy', no de la marca Mariola Onetti Designs. "
    "(3) Fuga de recursos por piratería: Etsy no logra detectar todas las copias y Mariola dedica buena "
    "parte de su jornada a pedir que retiren productos que copian su trabajo. "
    "(4) La paradoja del modelo de ingresos: la mayor parte de sus ingresos proviene de pedidos al por "
    "mayor de clientes que la contratan fuera de la plataforma. "
    "Alternativas: pasar de la dependencia a la omnicanalidad. Alternativa A (transición de marca propia): "
    "usar Pattern de Etsy (15 USD/mes) para migrar gradualmente su tráfico a un dominio propio. "
    "Alternativa B (pivotar a B2B): aceptar que Etsy es un generador de leads y centrar el modelo operativo "
    "en escalar los pedidos al por mayor que ya sustentan su empresa.",
    # A2 — evidencias del techo de cristal
    "Para sustentar el 'techo de cristal' me baso en tres evidencias concretas: "
    "(1) Estancamiento del crecimiento histórico: en 2018 una sola mención en Facebook le permitió vender "
    "1.600 camisetas en una semana; para 2019 alcanzó ingresos equivalentes a 1,3 millones de dólares; sin "
    "embargo el caso señala explícitamente que sus ventas 'parecían haberse estancado desde hace algún tiempo'. "
    "(2) Rendimiento decreciente del tiempo (tope operativo): dedica buena parte de su jornada a perseguir "
    "copias en vez de crecer — el esfuerzo marginal ya no genera ingresos marginales frente a miles de "
    "vendedores y millones de artículos similares. "
    "(3) Canibalización de marca y fuga de ingresos: los clientes no se fidelizan con ella (hablan de Etsy en "
    "redes) y la mayor parte de los ingresos proviene de pedidos al por mayor contratados fuera de la "
    "plataforma. En resumen: la estructura de Etsy no le permite escalar su marca, consume su tiempo en "
    "tareas no rentables y ya no es su principal fuente de facturación real.",
    # A3 — implicaciones de la fidelización retenida por la plataforma
    "Que la fidelización recaiga en la plataforma y no en el creador cambia la dinámica de poder del negocio. "
    "Implicaciones: (1) Pérdida del valor del ciclo de vida del cliente (LTV): Etsy capitaliza las compras "
    "recurrentes mientras Mariola pierde la relación directa; el mérito de la transacción es de Etsy. "
    "(2) Comoditización y vulnerabilidad estructural: sin marca fuerte sus productos se vuelven commodities; "
    "cualquier imitador con mejor precio o posicionamiento en el algoritmo le roba la venta, agravando el "
    "problema de las copias. Para el largo plazo, su estrategia debe pivotar de 'vendedora en un marketplace' "
    "a 'marca omnicanal': (a) desarrollo de canales propios direct-to-consumer (por ejemplo con Pattern) para "
    "capturar datos de clientes, hacer email marketing y construir comunidad; (b) estructuración del canal "
    "B2B: formalizar el modelo mayorista que ya sustenta sus ingresos y usar Etsy como catálogo de exhibición "
    "y generación de leads. En definitiva, usar el tráfico de Etsy para apalancar su propia marca, no al revés.",
    # A4 — obstáculos de la transición omnicanal
    "Tres obstáculos principales y cómo superarlos: (1) Costo de adquisición de clientes y tráfico: Etsy "
    "aporta decenas de millones de compradores por comisiones bajas (20 centavos por artículo y 3,5% por "
    "venta); al lanzar canal propio parte de cero en reconocimiento externo. Solución: 'migración suave' con "
    "cupones, tarjetas de agradecimiento y códigos QR en los paquetes de pedidos de Etsy, usando la "
    "plataforma como embudo de adquisición. (2) Falta de tiempo y desgaste operativo: construir canales "
    "nuevos requiere tiempo que hoy gasta persiguiendo copias — batalla perdida dada la magnitud del sitio; "
    "debe aceptarla como costo de hacer negocios y redirigir esas horas a prospección de clientes mayoristas. "
    "(3) Brecha tecnológica: montar tienda independiente la aleja de su núcleo creativo. Solución: usar "
    "Pattern (15 USD/mes) para tener dominio y marca propios sin abandonar la infraestructura de pagos que "
    "ya conoce.",
    # A5 — escenario de fracaso y mitigación
    "Si el canal DTC no tracciona, las consecuencias serían: dependencia perpetua y estancamiento (seguir "
    "compitiendo contra millones de artículos con la marca diluida), desgaste operativo crónico (seguir "
    "persiguiendo copias) y pérdida de la inversión y del costo de oportunidad del tiempo. Mitigación: "
    "(1) No quemar los barcos: mantener Etsy como 'vaca lechera' y escaparate — sin esa vitrina nunca "
    "habrían llegado los pedidos al por mayor; asumir las comisiones como gasto de relaciones públicas. "
    "(2) Blindar el canal mayorista: asegurar contratos B2B a largo plazo — si el canal propio falla, esos "
    "pedidos siguen sosteniendo la empresa. (3) Ejecutar con producto mínimo viable: probar tracción con "
    "herramientas de bajo riesgo como Pattern o las APIs de Etsy antes de escalar la inversión.",
    # A6 — papel de la retroalimentación
    "La voz del cliente es la brújula de la transición: (1) Recuperar el control de la narrativa: hoy opera a "
    "ciegas sobre la lealtad del consumidor final. (2) Segmentar la propuesta de valor entre el público "
    "minorista (mujeres jóvenes de 18-24 años) y los clientes corporativos mayoristas que sustentan la "
    "facturación. (3) Validar el producto frente a los estándares de experiencia de Etsy. Implementación sin "
    "sobrecargar su jornada: en B2C aprovechar el 'unboxing' (ella controla el paquete) con tarjetas y QR a "
    "una encuesta breve con descuento, y monitorear menciones en redes para redirigirlas a su marca; en B2B "
    "un CRM básico con entrevistas ejecutivas trimestrales a sus principales compradores y análisis de "
    "rotación de diseños para ajustar la producción de forma predictiva.",
    # A7 — desafíos del sistema de retroalimentación
    "Tres desafíos de ejecución: (1) Fatiga de encuestas y 'propiedad' del cliente: Etsy ya pide reseñas "
    "constantemente y el cliente siente que le compró a Etsy; la tasa de respuesta externa será baja. "
    "Solución: feedback invisible y transaccional vía QR impreso en el paquete con beneficio inmediato "
    "(15% de descuento en el próximo pedido). (2) Limitación de capacidad operativa: capturar datos es inútil "
    "sin horas para analizarlos; aplicar Pareto 80/20 — cesar la persecución de copias y dedicar ese tiempo "
    "al feedback cualitativo de los 5 grandes compradores B2B, más viable y rentable que mil encuestas "
    "minoristas. (3) Sesgo del creador frente a los datos: puede dolerle que un diseño que ama no tenga "
    "viabilidad comercial; validación objetiva con A/B testing en Pinterest antes de producir — los datos del "
    "mercado superan al sesgo creativo.",
]


def enviar(message, history, state):
    body = {
        "conversation_id": "prueba-entrevista-01",
        "user_id": "estudiante_prueba",
        "message": message,
        "history": history,
        "state": state,
    }
    res = httpx.post(URL, json=body, timeout=120)
    res.raise_for_status()
    return res.json()


transcript = []
history = []
state = {"current_question": 1, "turns_for_current_question": 0}

# Turno 0: apertura (sin mensaje, como hace el front al iniciar).
respuesta = enviar("", history, state)
transcript.append({"turno": 0, "state": dict(state), "student": "(apertura)", "response": respuesta})
history.append({"role": "assistant", "content": respuesta["message"]})

fin = False
for i, answer in enumerate(RESPUESTAS, start=1):
    if fin:
        transcript.append({"turno": i, "student": "(no enviado — la entrevista ya cerró)"})
        break
    respuesta = enviar(answer, history, state)
    transcript.append({"turno": i, "state": dict(state), "student": answer[:120] + "...", "response": respuesta})

    history.append({"role": "user", "content": answer})
    history.append({"role": "assistant", "content": respuesta["message"]})

    st = respuesta.get("structured") or {}
    if st.get("is_final_summary"):
        fin = True
    elif st.get("advance_to_next_question"):
        state["current_question"] += 1
        state["turns_for_current_question"] = 0
    else:
        state["turns_for_current_question"] += 1

with open("_sim_transcript.json", "w", encoding="utf-8") as f:
    json.dump(transcript, f, ensure_ascii=False, indent=2)

# Resumen compacto por consola.
for t in transcript:
    r = t.get("response")
    if not r:
        print(f"T{t['turno']}: {t['student']}")
        continue
    st = r.get("structured") or {}
    print(
        f"T{t['turno']} [Q{t['state']['current_question']} N{t['state']['turns_for_current_question']}] "
        f"rubric={st.get('rubric_level')} advance={st.get('advance_to_next_question')} "
        f"final={st.get('is_final_summary')} rag={r.get('rag_used')} sources={len(r.get('sources') or [])}"
    )
print("\nTranscript completo en _sim_transcript.json")
