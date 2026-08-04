def _resumen_costos_para_flujo(conn, temporada, fi, ff):
    """Resumen para Flujo financiero: solo gastos de la temporada (fi–ff).

    El módulo Costos vigente puede incluir movimientos pre-temporada; el Flujo
    no debe cargar esos egresos contra el presupuesto ni el EERR de la temporada.
    """
    prorrateo = cargar_prorrateo_cc(conn)
    matriz = _armar_matriz_costos_vista_b(
        conn, fi, ff, CUARTELES_OFICIALES, prorrateo, temporada,
    )
    return resumen_desde_matriz_costos(matriz, CUARTELES_OFICIALES)


