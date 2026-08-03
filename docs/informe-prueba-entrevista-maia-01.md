# Informe de desempeño — Replay "Prueba entrevista Maia 01"

**Fecha:** 2026-06-10
**Sistema bajo prueba:** runtime multi-agente (`prompt system-v4`, `vector_store v2`, 7 `hard_rules`, `gpt-4o-mini`)
**Baseline:** transcript del gem de Gemini (`260602 Prueba entrevista Maia 01.pdf`)
**Método:** se reenviaron las mismas 7 respuestas del estudiante, en el mismo orden, vía
`POST /api/agents/maia/chat`, simulando el tracking de estado del frontend
(avance → Q+1 y N=0; si no → N+1). Script reproducible: `scripts/replay_entrevista_maia.py`.
Transcript completo: `docs/prueba-entrevista-01-transcript.json`.

---

## 1. Resultados turno a turno

| Turno | Estado (Q, N) | Rúbrica | ¿Avanza? | ¿Cierre? | RAG | Comentario |
|---|---|---|---|---|---|---|
| T0 (apertura) | Q1, N0 | — | no | no | — | Abre con la pregunta 1 de introspección, igual que el gem |
| T1 (problema y alternativas) | Q1, N0 | satisfactorio | no | no | ✅ | Repregunta por evidencias (mismo movimiento que el gem) |
| T2 (evidencias del techo) | Q1, N1 | satisfactorio | no | no | ✅ (2 fuentes) | Repregunta por riesgos de la alternativa A |
| T3 (implicaciones fidelización) | Q1, N2 | satisfactorio | **sí** | no | ✅ | **Avanza a Q2** (regla: satisfactorio + N≥2) |
| T4 (obstáculos omnicanal) | Q2, N0 | satisfactorio | no | no | ✅ | Repregunta por sostenibilidad |
| T5 (fracaso y mitigación) | Q2, N1 | satisfactorio | **sí** | no | ✅ | **Avanza a Q3** (decisión propia del modelo) |
| T6 (voz del cliente) | Q3, N0 | satisfactorio | no | **sí** | ✅ | **Cierra con resumen final** + 2 `unresolved_points` |
| T7 | — | — | — | — | — | No se envió: la entrevista ya había cerrado |

**Duración total: 6 turnos de estudiante** (el gem necesitó 7 y nunca declaró avances).

## 2. Comparación con el gem (baseline del PDF)

| Dimensión | Gem (PDF) | Runtime nuevo |
|---|---|---|
| Avances de pregunta declarados | 0 explícitos — 7 repreguntas seguidas sobre el mismo hilo | 2 avances explícitos (T3, T5) + cierre (T6) |
| Turnos para completar | 7 (y el cierre llegó "de golpe") | 6, con progresión visible Q1→Q2→Q3 |
| Riesgo de retención infinita | Alto (dependía 100% del juicio del modelo) | **Eliminado**: `hard_rules` server-side garantizan los topes (N≥3 avanza, N≥4 nunca se excede) |
| Cierre con resumen + puntos abiertos | Sí | Sí (`is_final_summary` + `unresolved_points` poblados) |
| Estilo socrático (abogado del diablo, repreguntas dirigidas) | Sí | Sí — mismas familias de repregunta (evidencia, riesgo, sostenibilidad) |
| Uso del caso (RAG) | Implícito | Verificable: `rag_used: true` en todos los turnos con contenido |

## 3. Hallazgos de la prueba (y su resolución)

1. **Bug de borde detectado**: en la primera corrida, al estar en Q3 el modelo devolvió
   `advance_to_next_question: true` y la conversación "avanzó" a una **Q4 inexistente**, sin
   cerrar nunca. → Corregido con la `hard_rule` 7: *avanzar estando en Q≥3 = `is_final_summary`*.
   Cubierto por test unitario (`test_avance_del_modelo_en_q3_se_convierte_en_resumen_final`).
2. **El modelo califica conservador**: las 7 respuestas del PDF son de nivel claramente alto
   (evidencia citada, marcos LTV/CAC/MVP, mitigación de riesgos) y `gpt-4o-mini` las calificó
   todas `satisfactorio`. La vía rápida "superior/excelente → avance inmediato" nunca se activó;
   el avance llegó por la regla `satisfactorio + N≥2`. Ver recomendaciones.
3. **Limitación conocida del cierre forzado**: en T6 el flag `is_final_summary` lo forzó la
   hard rule, pero el `message` del modelo era una repregunta (no el resumen escrito). Los
   `unresolved_points` sí llegaron poblados. El frontend debe renderizar la pantalla de cierre
   a partir del flag + `unresolved_points` (mismo comportamiento que tenía el backend legacy
   con su force-advance).

## 4. Recomendaciones

- **Si quieren avance aún más ágil**: hay dos palancas, ambas sin tocar código:
  1. Regla más laxa en `config.json` (ej. `satisfactorio` → avance inmediato, N≥1).
  2. Mejor juez de rúbrica: cambiar `llm_model` a `gpt-4o` en el config (la fábrica de
     providers lo soporta) — calificaría `superior` las respuestas fuertes y activaría la vía rápida.
- **QA conversacional con estudiantes reales**: este replay usa respuestas "perfectas"; conviene
  validar con respuestas mediocres que la retención (N<2 con respuestas pobres) siga funcionando.
- **Mejora futura opcional**: cuando una hard rule fuerce `is_final_summary`, hacer una segunda
  llamada al LLM pidiendo el resumen escrito (costo: +1 llamada solo en ese turno).

## 5. Cómo reproducir

```powershell
# runtime corriendo en localhost:8000 con credenciales AWS + OPENAI_API_KEY
.venv\Scripts\python.exe scripts\replay_entrevista_maia.py
```
