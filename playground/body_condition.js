// A reading of retained native damage, not a fatigue/strength prediction.
export function conditionSummary(rows = []) {
  if (!rows.length) return {state:"unavailable", fraction:null, text:"Not reported"};
  if (rows.some(r => r.state === "unresolved")) return {state:"unresolved",fraction:null,text:"Checking damage"};
  if (rows.some(r => r.state === "broken")) return {state:"broken",fraction:0,text:"Broken"};
  if (rows.some(r => r.state === "unavailable")) return {state:"unavailable",fraction:null,text:"Not reported"};
  if (rows.some(r => r.state !== "measured" || !Number.isFinite(r.fraction)))
    return {state:"unmodeled",fraction:null,text:"Not modeled"};
  const fraction=Math.max(0,Math.min(1,...rows.map(r=>r.fraction)));
  const percent=fraction*100;
  // A real small cut must remain visible instead of rounding back to 100%.
  return {state:"measured",fraction,text:percent < 100 && percent >= 99.95 ? "<100%" : `${percent === 100 ? "100" : percent.toLocaleString(undefined,{maximumFractionDigits:1})}%`};
}

export function conditionPanel(rows, {label="Condition"} = {}) {
  const reading=conditionSummary(rows);
  const panel=document.createElement("section");panel.className="body-condition";
  panel.dataset.conditionState=reading.state;
  const line=document.createElement("div");line.className="condition-value";
  const name=document.createElement("span");name.textContent=label;
  const value=document.createElement("strong");value.textContent=reading.text;line.append(name,value);panel.append(line);
  panel.title="Recorded bond continuity and supported current thermal section factors. No fatigue or strength certification. Exact rigid parts have no internal damage model.";
  if (reading.fraction !== null) {
    const meter=document.createElement("meter");meter.min=0;meter.max=1;meter.value=reading.fraction;
    meter.setAttribute("aria-label",`${label}: ${reading.text}`);panel.append(meter);
  }
  if(rows?.length) {
    const details=document.createElement("details"),summary=document.createElement("summary");
    summary.textContent="Damage details";details.append(summary);
    for(const row of rows) {
      const part=document.createElement("p");
      const bonds=row.bonds ? `${row.broken_bonds} / ${row.bonds} broken bonds` : "No bond damage model";
      const heat=Number.isFinite(row.thermal_fraction) ? `Heat section: ${(100*row.thermal_fraction).toFixed(1)}%` : "Heat section: not modeled / untracked";
      part.textContent=`${row.name} · ${bonds} · ${heat}${row.dent_mm>0 ? ` · Dent: ${row.dent_mm.toFixed(2)} mm` : ""}`;
      details.append(part);
    }
    const scope=document.createElement("p");scope.textContent="Current retained connections; heat can soften or permanently damage material. Dents are separate. Use alone does not yet cause fatigue. Repair is not available yet.";
    details.append(scope);panel.append(details);
  }
  return panel;
}
