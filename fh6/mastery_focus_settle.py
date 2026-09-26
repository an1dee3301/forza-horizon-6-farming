"""Input-free focus polling for normal fast mastery movement."""
import time


def target_ready(result, name):
    return (result.get('screen')=='mad_mike_mastery'
            and result.get('selection',{}).get('name')==name
            and result.get('nodes',{}).get(name,{}).get('state')=='available')


def settle(observe, check, pause, name, *, clock=time.monotonic):
    """Poll within .35s after one arrow; timeout requests one fresh fallback.

    A returned observation is only the first of the existing three pre-Enter
    proofs. No ownership proof count changes. Capture calls are synchronous;
    a late capture cannot authorize an early handoff.
    """
    start=clock();deadline=start+.35;captures=0
    while clock()<deadline:
        check()
        frame,result=observe(allow_transition=True);captures+=1
        if clock()>=deadline:break
        if target_ready(result,name):
            check()
            return (frame,result),clock()-start,captures
        pause(min(.02,max(0.,deadline-clock())))
    return None,clock()-start,captures
