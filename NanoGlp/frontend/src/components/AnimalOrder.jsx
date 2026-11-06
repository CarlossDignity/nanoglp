import React, {useState} from 'react';
export default function AnimalOrder({ step, busy, onAction }) {
  const state=step.animal_order;
  const [orderDate,setOrderDate]=useState(step.order_defaults?.order_date || '');
  const [days,setDays]=useState(step.order_defaults?.estimated_delivery_days ?? 15);
  const [received,setReceived]=useState(step.order_defaults?.order_date || '');
  return <div className="text-xs space-y-2 mt-2" data-testid="animal-order">
    {step.animal_status && <p className="font-semibold">{step.animal_status}</p>}
    {state?.order_date && <p>Sipariş: {state.order_date} · {state.ordered_by} · Tahmini geliş: {state.expected_delivery_date} ({state.estimated_delivery_days} takvim günü)</p>}
    {state?.received_date && <p>Kabul: {state.received_date} · {state.received_by}</p>}
    {!state && step.done && <p>Eski tamamlanma kaydı; sipariş/kabul ayrıntıları kayıtlı değil.</p>}
    {step.can_edit && <>
      {!state?.order_date && !step.done && <div className="flex flex-wrap gap-2">
        <label>Sipariş tarihi <input aria-label="Sipariş tarihi" type="date" value={orderDate} onChange={e=>setOrderDate(e.target.value)} /></label>
        <label>Tahmini teslim (gün) <input aria-label="Tahmini teslim günleri" type="number" min="0" value={days} onChange={e=>setDays(e.target.value)} /></label>
        <button disabled={busy || !orderDate || days === '' || Number(days)<0} onClick={()=>onAction({action:'order',order_date:orderDate,estimated_delivery_days:Number(days)})}>Siparişi Kaydet</button>
      </div>}
      {state?.order_date && !state.received_date && <div className="flex flex-wrap gap-2">
        <label>Kabul tarihi <input aria-label="Kabul tarihi" type="date" min={state.order_date} value={received} onChange={e=>setReceived(e.target.value)} /></label>
        <button disabled={busy || !received} onClick={()=>onAction({action:'receive',received_date:received})}>Kabulü Onayla</button>
      </div>}
      {(state?.order_date || step.done) && <button disabled={busy} onClick={()=>onAction({action:'undo'})}>{state?.received_date ? 'Kabulü Geri Al' : state?.order_date ? 'Siparişi Geri Al' : 'Geri Al'}</button>}
    </>}
  </div>;
}
