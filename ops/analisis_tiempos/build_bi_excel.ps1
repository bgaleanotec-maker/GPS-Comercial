# Paso 2 del Excel BI: con Excel (COM) crea tablas dinamicas, segmentadores, linea de tiempo,
# graficos dinamicos, tarjetas KPI y formato condicional sobre el libro base de build_bi_data.py.
# Uso: powershell -File build_bi_excel.ps1 -In base.xlsx -Out VantiGo_BI_Tiempos.xlsx
# (solo caracteres ASCII en este archivo: PowerShell 5.1 lo lee como ANSI)
param([string]$In, [string]$Out)
$ErrorActionPreference = 'Stop'
$In = [System.IO.Path]::GetFullPath($In); $Out = [System.IO.Path]::GetFullPath($Out)
if (Test-Path $Out) { Remove-Item $Out -Force }
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false; $xl.ScreenUpdating = $false
$M = [Type]::Missing
try {
  $wb = $xl.Workbooks.Open($In)
  $xlDatabase = 1; $xlRow = 1; $xlColumn = 2
  $xlSum = -4157; $xlAverage = -4106; $xlCount = -4112; $xlMax = -4136
  # Formatos en notacion LOCAL (Excel en espanol: coma decimal, punto de miles)
  $F1 = '#.##0,0'; $F0 = '#.##0'; $F2 = '#.##0,00'; $FP = '0%'; $FH = '#.##0,00" h"'
  $BG = 0x2E1A0F; $CARD = 0x4A2E1A; $LINE = 0x6B4F3A; $GOLD = 0xF8CF81; $TXT = 0xF9F5F1; $MUTED = 0xB8A394; $GRID = 0x5A4030

  $dash = $wb.Worksheets.Add($wb.Worksheets.Item(1)); $dash.Name = 'Dashboard BI'
  $dash.Tab.Color = 0xE56346
  $dash.Cells.Interior.Color = $BG; $dash.Cells.Font.Name = 'Segoe UI'; $dash.Cells.Font.Color = $TXT
  $dash.Activate(); $xl.ActiveWindow.DisplayGridlines = $false; $xl.ActiveWindow.Zoom = 85
  for ($c = 1; $c -le 60; $c++) { $dash.Columns.Item($c).ColumnWidth = 3.2 }
  $dash.Range('B2').Value2 = 'VantiGo - DASHBOARD BI - Uso del tiempo y vigilancia operacional'
  $dash.Range('B2').Font.Size = 20; $dash.Range('B2').Font.Bold = $true; $dash.Range('B2').Font.Color = $GOLD
  $dash.Range('B3').Value2 = 'Horario 06:00-20:00, lunes a viernes - GPS depurado - Usa los segmentadores (Segmento, Ejecutivo, Mes, Dia) y la linea de tiempo: todo el tablero se filtra a la vez.'
  $dash.Range('B3').Font.Size = 10; $dash.Range('B3').Font.Color = $MUTED

  # ---------- Tablas dinamicas (misma cache -> segmentadores compartidos) ----------
  $cache = $wb.PivotCaches().Create($xlDatabase, 'tblDiario')
  $pv = $wb.Worksheets.Add(); $pv.Name = 'PivotData'
  function New-Pivot($name, $cell, $rowField) {
    $pt = $cache.CreatePivotTable($pv.Range($cell), $name)
    if ($rowField) { $pt.PivotFields($rowField).Orientation = $xlRow }
    return $pt
  }
  # Totales para tarjetas KPI (sin campo de filas: valores en la fila 2, columnas A..K)
  $ptT = New-Pivot 'ptTotales' 'A1' $null
  $ptT.AddDataField($ptT.PivotFields('Km'), 'Km total', $xlSum) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Jornada h'), 'Jornada prom', $xlAverage) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Paradas productivas'), 'Prod prom', $xlAverage) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Fecha'), 'Dias', $xlCount) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Min en base'), 'Min base', $xlSum) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Min detenido'), 'Min det', $xlSum) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Min movimiento'), 'Min mov', $xlSum) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Exceso >80'), 'Dias exceso', $xlSum) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Tiempos muertos'), 'Muertos', $xlSum) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Horas fuera base'), 'Horas fuera', $xlAverage) | Out-Null
  $ptT.AddDataField($ptT.PivotFields('Km'), 'Km prom', $xlAverage) | Out-Null
  $ptM = New-Pivot 'ptMes' 'A20' 'Mes'
  $ptM.AddDataField($ptM.PivotFields('Km'), 'Km por dia', $xlAverage) | Out-Null
  $ptM.AddDataField($ptM.PivotFields('Paradas productivas'), 'Paradas prod. por dia', $xlAverage) | Out-Null
  $ptMD = New-Pivot 'ptMesDias' 'F20' 'Mes'
  $ptMD.AddDataField($ptMD.PivotFields('Fecha'), 'Dias-persona', $xlCount) | Out-Null
  $ptMD.AddDataField($ptMD.PivotFields('Exceso >80'), 'Dias con exceso', $xlSum) | Out-Null
  $ptEK = New-Pivot 'ptEjecKm' 'A60' 'Empleado'
  $ptEK.AddDataField($ptEK.PivotFields('Km'), 'Km/dia', $xlAverage) | Out-Null
  $ptEP = New-Pivot 'ptEjecProd' 'F60' 'Empleado'
  $ptEP.AddDataField($ptEP.PivotFields('Paradas productivas'), 'Paradas prod./dia', $xlAverage) | Out-Null
  $ptEP.AddDataField($ptEP.PivotFields('Tiempos muertos'), 'T. muertos/dia', $xlAverage) | Out-Null
  $ptU = New-Pivot 'ptUso' 'A100' 'Empleado'
  $ptU.AddDataField($ptU.PivotFields('Min en base'), 'En base', $xlSum) | Out-Null
  $ptU.AddDataField($ptU.PivotFields('Min productivos'), 'Productivo', $xlSum) | Out-Null
  $ptU.AddDataField($ptU.PivotFields('Min tiempo muerto'), 'Tiempo muerto', $xlSum) | Out-Null
  $ptU.AddDataField($ptU.PivotFields('Min movimiento'), 'Movimiento', $xlSum) | Out-Null
  $ptD = New-Pivot 'ptDia' 'A140' 'Dia semana'
  $ptD.AddDataField($ptD.PivotFields('Km'), 'Km por dia', $xlAverage) | Out-Null
  $ptD.AddDataField($ptD.PivotFields('Paradas productivas'), 'Paradas prod.', $xlAverage) | Out-Null
  $ptS = New-Pivot 'ptSeg' 'A160' 'Segmento'
  $ptS.AddDataField($ptS.PivotFields('Km'), 'Km/dia', $xlAverage) | Out-Null
  $ptS.AddDataField($ptS.PivotFields('Jornada h'), 'Jornada (h)', $xlAverage) | Out-Null
  $ptS.AddDataField($ptS.PivotFields('Paradas productivas'), 'Paradas prod./dia', $xlAverage) | Out-Null
  $ptS.AddDataField($ptS.PivotFields('Horas fuera base'), 'Horas fuera de base', $xlAverage) | Out-Null
  $ptSV = New-Pivot 'ptSegVel' 'F160' 'Segmento'
  $ptSV.AddDataField($ptSV.PivotFields('Exceso >80'), 'Dias con exceso', $xlSum) | Out-Null
  $ptSV.AddDataField($ptSV.PivotFields('Tiempos muertos'), 'T. muertos (total)', $xlSum) | Out-Null
  $all = @($ptT, $ptM, $ptMD, $ptEK, $ptEP, $ptU, $ptD, $ptS, $ptSV)
  foreach ($pt in $all) { $pt.TableStyle2 = 'PivotStyleMedium2'; try { $pt.DataBodyRange.NumberFormatLocal = $F1 } catch {} }
  try { $ptD.PivotFields('Dia semana').PivotItems('Lunes').Position = 1; $ptD.PivotFields('Dia semana').PivotItems('Martes').Position = 2; $ptD.PivotFields('Dia semana').PivotItems('Miercoles').Position = 3; $ptD.PivotFields('Dia semana').PivotItems('Jueves').Position = 4; $ptD.PivotFields('Dia semana').PivotItems('Viernes').Position = 5 } catch {}

  # ---------- Segmentadores y linea de tiempo ----------
  $scSeg = $wb.SlicerCaches.Add2($ptT, 'Segmento'); $scEmp = $wb.SlicerCaches.Add2($ptT, 'Empleado'); $scMes = $wb.SlicerCaches.Add2($ptT, 'Mes'); $scDia = $wb.SlicerCaches.Add2($ptT, 'Dia semana')
  $tl = $wb.SlicerCaches.Add2($ptT, 'Fecha', $M, 2)
  foreach ($sc in @($scSeg, $scEmp, $scMes, $scDia, $tl)) { foreach ($pt in $all) { if ($pt.Name -ne 'ptTotales') { $sc.PivotTables.AddPivotTable($pt) } } }
  $s = $scSeg.Slicers.Add($dash, $M, 'Segmento', 'Segmento', 95, 20, 180, 80); try { $s.NumberOfColumns = 2; $s.Style = 'SlicerStyleDark1' } catch {}
  $s = $scEmp.Slicers.Add($dash, $M, 'Ejecutivo', 'Ejecutivo', 95, 210, 560, 80); try { $s.NumberOfColumns = 7; $s.Style = 'SlicerStyleDark1' } catch {}
  $s = $scMes.Slicers.Add($dash, $M, 'Mes', 'Mes', 95, 780, 440, 80); try { $s.NumberOfColumns = 5; $s.Style = 'SlicerStyleDark1' } catch {}
  $s = $scDia.Slicers.Add($dash, $M, 'Dia', 'Dia de la semana', 95, 1230, 230, 80); try { $s.NumberOfColumns = 3; $s.Style = 'SlicerStyleDark1' } catch {}
  $t1 = $tl.Slicers.Add($dash, $M, 'LineaTiempo', 'Periodo (arrastra para elegir fechas)', 180, 20, 1330, 70); try { $t1.Style = 'TimeSlicerStyleDark1' } catch {}

  # ---------- Tarjetas KPI ----------
  $kp = @(
    @('Km recorridos', '=PivotData!A2', $F0, 'km en el filtro'),
    @('Km por dia', '=PivotData!K2', $F1, 'promedio por dia-persona'),
    @('Dias con datos', '=PivotData!D2', $F0, 'dias-persona'),
    @('Jornada promedio', '=PivotData!B2', $FH, 'primer a ultimo GPS'),
    @('Paradas productivas', '=PivotData!C2', $F2, 'por dia (>=20 min fuera de base)'),
    @('% tiempo en base', '=IFERROR(PivotData!E2/(PivotData!F2+PivotData!G2),0)', $FP, 'domicilio/base en horario'),
    @('% en movimiento', '=IFERROR(PivotData!G2/(PivotData!F2+PivotData!G2),0)', $FP, 'del tiempo laboral'),
    @('Tiempos muertos', '=PivotData!I2', $F0, 'paradas >=2 h fuera de base'),
    @('Dias con exceso >80', '=PivotData!H2', $F0, 'conduccion segura'),
    @('Horas fuera de base', '=PivotData!J2', $FH, 'salida a regreso')
  )
  $left = 20; $top = 262; $w = 128; $h = 72; $i = 0
  foreach ($k in $kp) {
    $x = $left + $i * ($w + 6)
    $shp = $dash.Shapes.AddShape(5, $x, $top, $w, $h); $shp.Fill.ForeColor.RGB = $CARD; $shp.Line.ForeColor.RGB = $LINE; $shp.Line.Weight = 0.75; $shp.Name = 'kpiBox' + $i
    $cell = $pv.Range('B' + (200 + $i)); $cell.Formula = $k[1]; $cell.NumberFormatLocal = $k[2]
    $tv = $dash.Shapes.AddTextbox(1, $x + 6, $top + 6, $w - 12, 34); $tv.Name = 'kpiVal' + $i
    $tv.DrawingObject.Formula = '=PivotData!B' + (200 + $i)
    $tv.TextFrame.Characters().Font.Size = 20; $tv.TextFrame.Characters().Font.Bold = $true; $tv.TextFrame.Characters().Font.Color = $GOLD; $tv.Fill.Visible = 0; $tv.Line.Visible = 0
    $tl1 = $dash.Shapes.AddTextbox(1, $x + 6, $top + 40, $w - 12, 14); $tl1.TextFrame.Characters().Text = $k[0]; $tl1.TextFrame.Characters().Font.Size = 9; $tl1.TextFrame.Characters().Font.Bold = $true; $tl1.TextFrame.Characters().Font.Color = 0xFFFFFF; $tl1.Fill.Visible = 0; $tl1.Line.Visible = 0
    $tl2 = $dash.Shapes.AddTextbox(1, $x + 6, $top + 54, $w - 12, 14); $tl2.TextFrame.Characters().Text = $k[3]; $tl2.TextFrame.Characters().Font.Size = 7.5; $tl2.TextFrame.Characters().Font.Color = $MUTED; $tl2.Fill.Visible = 0; $tl2.Line.Visible = 0
    $i++
  }

  # ---------- Graficos dinamicos ----------
  function Add-PChart($pt, $type, $left, $top, $w, $h, $title) {
    $ch = $dash.Shapes.AddChart2(-1, $type, $left, $top, $w, $h).Chart
    $ch.SetSourceData($pt.TableRange1)
    $ch.HasTitle = $true; $ch.ChartTitle.Text = $title; $ch.ChartTitle.Font.Size = 11; $ch.ChartTitle.Font.Bold = $true; $ch.ChartTitle.Font.Color = 0xFFFFFF
    $ch.ChartArea.Format.Fill.ForeColor.RGB = $CARD; $ch.ChartArea.Format.Line.ForeColor.RGB = $LINE; $ch.PlotArea.Format.Fill.Visible = 0
    try { $ch.Axes(1).TickLabels.Font.Color = 0xDDD0C8; $ch.Axes(1).TickLabels.Font.Size = 8; $ch.Axes(2).TickLabels.Font.Color = 0xDDD0C8; $ch.Axes(2).TickLabels.Font.Size = 8; $ch.Axes(2).MajorGridlines.Format.Line.ForeColor.RGB = $GRID } catch {}
    try { $ch.Legend.Font.Color = 0xDDD0C8; $ch.Legend.Position = -4107; $ch.Legend.Font.Size = 8 } catch {}
    try { $ch.PivotLayout.ShowAllFieldButtons = $false } catch {}
    return $ch
  }
  $c1 = Add-PChart $ptM 4 20 345 440 230 'Km por dia y paradas productivas por mes'
  try { $c1.SeriesCollection(2).AxisGroup = 2; $c1.Axes(2, 2).TickLabels.Font.Color = 0xDDD0C8 } catch {}
  $c2 = Add-PChart $ptEK 57 470 345 440 330 'Km por dia por ejecutivo'
  try { $c2.ChartGroups(1).GapWidth = 50; $c2.HasLegend = $false; $c2.SeriesCollection(1).Format.Fill.ForeColor.RGB = $GOLD } catch {}
  $c3 = Add-PChart $ptU 58 920 345 430 330 'Uso del tiempo por ejecutivo (minutos acumulados)'
  try { $c3.ChartGroups(1).GapWidth = 40; $c3.SeriesCollection(1).Format.Fill.ForeColor.RGB = 0x4444EF; $c3.SeriesCollection(2).Format.Fill.ForeColor.RGB = 0x81B910; $c3.SeriesCollection(3).Format.Fill.ForeColor.RGB = 0x0B9EF5; $c3.SeriesCollection(4).Format.Fill.ForeColor.RGB = 0xF8BD38 } catch {}
  $c4 = Add-PChart $ptD 51 20 585 440 220 'Km por dia y paradas productivas por dia de la semana'
  try { $c4.SeriesCollection(2).AxisGroup = 2; $c4.SeriesCollection(2).ChartType = 4 } catch {}
  $c5 = Add-PChart $ptS 51 20 815 440 240 'Comparativo por segmento (promedios por dia)'
  $c6 = Add-PChart $ptEP 51 470 685 440 370 'Paradas productivas y tiempos muertos por dia, por ejecutivo'
  try { $c6.SeriesCollection(1).Format.Fill.ForeColor.RGB = 0x81B910; $c6.SeriesCollection(2).Format.Fill.ForeColor.RGB = 0x4444EF } catch {}
  $c7 = Add-PChart $ptMD 51 920 685 430 370 'Dias con datos y dias con exceso de velocidad por mes'
  try { $c7.SeriesCollection(2).Format.Fill.ForeColor.RGB = 0x4444EF } catch {}
  $c8 = Add-PChart $ptSV 51 920 1065 430 240 'Dias con exceso y tiempos muertos por segmento'

  # ---------- Ranking (dinamica visible con formato condicional) ----------
  $dash.Range('B86').Value2 = 'Ranking por ejecutivo (se filtra con los segmentadores; clic en los encabezados para ordenar)'; $dash.Range('B86').Font.Bold = $true; $dash.Range('B86').Font.Size = 12; $dash.Range('B86').Font.Color = $GOLD
  $ptR = $cache.CreatePivotTable($dash.Range('B88'), 'ptRanking')
  $ptR.PivotFields('Empleado').Orientation = $xlRow
  $ptR.AddDataField($ptR.PivotFields('Fecha'), 'Dias', $xlCount) | Out-Null
  $ptR.AddDataField($ptR.PivotFields('Km'), 'Km/dia', $xlAverage) | Out-Null
  $ptR.AddDataField($ptR.PivotFields('Jornada h'), 'Jornada (h)', $xlAverage) | Out-Null
  $ptR.AddDataField($ptR.PivotFields('Paradas productivas'), 'Paradas prod./dia', $xlAverage) | Out-Null
  $ptR.AddDataField($ptR.PivotFields('Min en base'), 'Min base/dia', $xlAverage) | Out-Null
  $ptR.AddDataField($ptR.PivotFields('Tiempos muertos'), 'T. muertos', $xlSum) | Out-Null
  $ptR.AddDataField($ptR.PivotFields('Exceso >80'), 'Dias exceso', $xlSum) | Out-Null
  $ptR.AddDataField($ptR.PivotFields('Vmax'), 'Vel. max', $xlMax) | Out-Null
  $ptR.AddDataField($ptR.PivotFields('Horas fuera base'), 'Horas fuera de base', $xlAverage) | Out-Null
  $ptR.TableStyle2 = 'PivotStyleDark2'
  try { $ptR.DataBodyRange.NumberFormatLocal = $F1 } catch {}
  foreach ($n in @('Dias', 'Min base/dia', 'T. muertos', 'Dias exceso', 'Vel. max')) { try { $ptR.PivotFields($n).DataRange.NumberFormatLocal = $F0 } catch {} }
  foreach ($sc in @($scSeg, $scEmp, $scMes, $scDia, $tl)) { $sc.PivotTables.AddPivotTable($ptR) }
  try { $ptR.PivotFields('Empleado').AutoSort(2, 'Km/dia') } catch {}
  $cols = @{ 'Km/dia' = 1; 'Paradas prod./dia' = 2; 'Min base/dia' = 3; 'T. muertos' = 3; 'Dias exceso' = 3; 'Vel. max' = 3 }
  foreach ($name in $cols.Keys) {
    $rng = $ptR.PivotFields($name).DataRange
    if ($cols[$name] -eq 1) { $db = $rng.FormatConditions.AddDatabar(); $db.BarColor.Color = $GOLD }
    elseif ($cols[$name] -eq 2) { $db = $rng.FormatConditions.AddDatabar(); $db.BarColor.Color = 0x81B910 }
    else { $cs = $rng.FormatConditions.AddColorScale(3); $cs.ColorScaleCriteria.Item(1).FormatColor.Color = 0x81B910; $cs.ColorScaleCriteria.Item(2).FormatColor.Color = 0x00D7FF; $cs.ColorScaleCriteria.Item(3).FormatColor.Color = 0x4444EF }
  }
  for ($c = 2; $c -le 12; $c++) { $dash.Columns.Item($c).ColumnWidth = 11 }
  $dash.Columns.Item(2).ColumnWidth = 15

  # ---------- Hoja Paradas BI ----------
  $pp = $wb.Worksheets.Add($wb.Worksheets.Item(2)); $pp.Name = 'Paradas BI'; $pp.Tab.Color = 0x81B910
  $pp.Cells.Interior.Color = $BG; $pp.Cells.Font.Color = $TXT; $pp.Cells.Font.Name = 'Segoe UI'
  $pp.Range('B2').Value2 = 'Paradas: donde, cuanto y a que hora (se filtra con sus segmentadores)'; $pp.Range('B2').Font.Size = 16; $pp.Range('B2').Font.Bold = $true; $pp.Range('B2').Font.Color = $GOLD
  $pp.Range('B3').Value2 = 'Tipo de parada: En base/domicilio - Productiva (>=20 min fuera de base) - Tiempo muerto (>=2 h fuera de base) - Corta (<20 min)'; $pp.Range('B3').Font.Size = 10; $pp.Range('B3').Font.Color = $MUTED
  $cache2 = $wb.PivotCaches().Create($xlDatabase, 'tblParadas')
  $ptP = $cache2.CreatePivotTable($pp.Range('B12'), 'ptParadasTipo')
  $ptP.PivotFields('Empleado').Orientation = $xlRow; $ptP.PivotFields('Tipo parada').Orientation = $xlColumn
  $ptP.AddDataField($ptP.PivotFields('Duracion h'), 'Horas', $xlSum) | Out-Null
  $ptP.TableStyle2 = 'PivotStyleDark2'; try { $ptP.DataBodyRange.NumberFormatLocal = $F1 } catch {}
  $ptH = $cache2.CreatePivotTable($pp.Range('P12'), 'ptParadasHora')
  $ptH.PivotFields('Hora llegada').Orientation = $xlRow; $ptH.PivotFields('Dia semana').Orientation = $xlColumn
  $ptH.AddDataField($ptH.PivotFields('Duracion min'), 'Paradas', $xlCount) | Out-Null
  $ptH.TableStyle2 = 'PivotStyleDark2'
  try { $ptH.PivotFields('Dia semana').PivotItems('Lunes').Position = 1; $ptH.PivotFields('Dia semana').PivotItems('Martes').Position = 2; $ptH.PivotFields('Dia semana').PivotItems('Miercoles').Position = 3; $ptH.PivotFields('Dia semana').PivotItems('Jueves').Position = 4; $ptH.PivotFields('Dia semana').PivotItems('Viernes').Position = 5 } catch {}
  $csH = $ptH.DataBodyRange.FormatConditions.AddColorScale(2); $csH.ColorScaleCriteria.Item(1).FormatColor.Color = $CARD; $csH.ColorScaleCriteria.Item(2).FormatColor.Color = $GOLD
  $ptL = $cache2.CreatePivotTable($pp.Range('P36'), 'ptParadasLugar')
  $ptL.PivotFields('Empleado').Orientation = $xlRow; $ptL.PivotFields('Lugar frecuente').Orientation = $xlRow
  $ptL.AddDataField($ptL.PivotFields('Duracion h'), 'Horas', $xlSum) | Out-Null
  $ptL.AddDataField($ptL.PivotFields('Duracion min'), 'Veces', $xlCount) | Out-Null
  $ptL.TableStyle2 = 'PivotStyleDark2'; $ptL.RowAxisLayout(2)   # 2 = xlOutlineRow
  try { $ptL.PivotFields('Horas').DataRange.NumberFormatLocal = $F1; $ptL.PivotFields('Lugar frecuente').AutoSort(2, 'Horas'); $ptL.PivotFields('Empleado').ShowDetail = $false } catch {}
  $pp.Range('P34').Value2 = 'Lugares frecuentes por ejecutivo (clic en + para desplegar)'; $pp.Range('P34').Font.Bold = $true; $pp.Range('P34').Font.Color = $GOLD
  $scP1 = $wb.SlicerCaches.Add2($ptP, 'Segmento'); $scP2 = $wb.SlicerCaches.Add2($ptP, 'Empleado'); $scP3 = $wb.SlicerCaches.Add2($ptP, 'Tipo parada'); $scP4 = $wb.SlicerCaches.Add2($ptP, 'Mes')
  foreach ($sc in @($scP1, $scP2, $scP3, $scP4)) { $sc.PivotTables.AddPivotTable($ptH); $sc.PivotTables.AddPivotTable($ptL) }
  $x = $scP1.Slicers.Add($pp, $M, 'SegP', 'Segmento', 50, 20, 180, 70); try { $x.NumberOfColumns = 1; $x.Style = 'SlicerStyleDark1' } catch {}
  $x = $scP2.Slicers.Add($pp, $M, 'EmpP', 'Ejecutivo', 50, 210, 560, 70); try { $x.NumberOfColumns = 7; $x.Style = 'SlicerStyleDark1' } catch {}
  $x = $scP3.Slicers.Add($pp, $M, 'TipoP', 'Tipo de parada', 50, 780, 300, 70); try { $x.NumberOfColumns = 2; $x.Style = 'SlicerStyleDark1' } catch {}
  $x = $scP4.Slicers.Add($pp, $M, 'MesP', 'Mes', 50, 1090, 440, 70); try { $x.NumberOfColumns = 5; $x.Style = 'SlicerStyleDark1' } catch {}
  $chP = $pp.Shapes.AddChart2(-1, 52, 20, 560, 640, 330).Chart; $chP.SetSourceData($ptP.TableRange1); $chP.HasTitle = $true; $chP.ChartTitle.Text = 'Horas por tipo de parada y ejecutivo'
  $chP.ChartArea.Format.Fill.ForeColor.RGB = $CARD; try { $chP.PivotLayout.ShowAllFieldButtons = $false; $chP.ChartTitle.Font.Color = 0xFFFFFF; $chP.Axes(1).TickLabels.Font.Color = 0xDDD0C8; $chP.Axes(2).TickLabels.Font.Color = 0xDDD0C8; $chP.Legend.Font.Color = 0xDDD0C8; $chP.Legend.Position = -4107; $chP.PlotArea.Format.Fill.Visible = 0 } catch {}
  $pp.Activate(); $xl.ActiveWindow.DisplayGridlines = $false; $xl.ActiveWindow.Zoom = 85

  # ---------- Formato condicional en Datos_KPI ----------
  $wk = $wb.Worksheets.Item('Datos_KPI'); $lo = $wk.ListObjects.Item('tblKPI')
  foreach ($cn in @('Indice operativo', 'Km/dia', 'Paradas productivas/dia', 'Cobertura GPS %')) { try { $db = $lo.ListColumns.Item($cn).DataBodyRange.FormatConditions.AddDatabar(); $db.BarColor.Color = 0xE5A163 } catch {} }
  foreach ($cn in @('% tiempo en base', '% dias con exceso', 'Tiempos muertos (h)', 'Radio P80 (km)')) { try { $cs = $lo.ListColumns.Item($cn).DataBodyRange.FormatConditions.AddColorScale(3); $cs.ColorScaleCriteria.Item(1).FormatColor.Color = 0x81B910; $cs.ColorScaleCriteria.Item(2).FormatColor.Color = 0x00D7FF; $cs.ColorScaleCriteria.Item(3).FormatColor.Color = 0x4444EF } catch {} }
  try { $lo.ListColumns.Item('Indice operativo').DataBodyRange.FormatConditions.AddIconSetCondition() | Out-Null } catch {}

  $pv.Visible = 0
  $dash.Activate(); $dash.Range('A1').Select() | Out-Null
  $wb.SaveAs($Out, 51)
  "OK -> $Out | caches: $($wb.PivotCaches().Count) | slicers: $($wb.SlicerCaches.Count)"
  $wb.Close($false)
} finally { $xl.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null }
