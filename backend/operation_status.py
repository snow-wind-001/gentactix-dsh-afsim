"""Read-only public operation facts, separate from physical simulation time."""

CLOCK_FIELDS=('started_at_ms','wall_elapsed_ms','clock_sampled_at_ms')


def view(session):
    observer=session.get('active_observer')
    meta=session.get('engine_last_meta') or {}
    failed=(session.get('failed_operations') or [None])[-1]
    completed=({k:meta[k] for k in ('operation_id','label','finish_reason',*CLOCK_FIELDS) if k in meta}
               if meta.get('operation_id') else None)
    failure=({k:failed[k] for k in ('operation_id','label','phase','turn','status','error','cancelled',*CLOCK_FIELDS) if k in failed}
             if failed and failed.get('operation_id') else None)
    candidates=[]
    if completed:candidates.append({**completed,'outcome':'success'})
    if failure:candidates.append({**failure,'outcome':'cancelled' if failure.get('cancelled') else 'failed'})
    known=[c for c in candidates if type(c.get('clock_sampled_at_ms')) is int]
    latest=max(known,key=lambda c:c['clock_sampled_at_ms']) if known else candidates[0] if len(candidates)==1 else None
    if len(known)==2 and known[0]['clock_sampled_at_ms']==known[1]['clock_sampled_at_ms']:
        latest=known[1] if known[0]['operation_id']==known[1]['operation_id'] else None
    progress={**dict(session.get('progress') or {}),**observer.clock_snapshot()} if observer else {}
    return dict(active=observer is not None,progress=progress,operation_id=observer.operation_id if observer else None,
        completed_operation=completed,failed_operation=failure,last_operation=latest)
