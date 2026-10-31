"""Isolated read-only PO-33 modem packet verifier (requires NumPy).

Executes in its own Python process; never emits reconstructed sounds or projects.
Upstream decoder: danielpradilla/po-backup-decode (MIT, vendor/PO33_DECODER_LICENSE.txt).
"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))

def run(path):
    try:
        from po33_decode import demodulate, parse_packets, collect_objects
    except ImportError:
        return {'payload_verified':False,'status':'NUMPY_REQUIRED',
                'detail':'Optional NumPy dependency is required for PO-33 modem verification.'}
    data,signal=demodulate(Path(path))
    packets,_,consumed=parse_packets(data)
    patterns,roots,entries,configs=collect_objects(packets)
    if (not packets or packets[-1][0]!=0x826f or len(patterns)!=16
            or len(configs)!=2 or len(entries)>136):
        raise ValueError('Incomplete PO-33 transfer structure')
    return {'payload_verified':True,'status':'PROTOCOL_CHECKSUM_VERIFIED',
            'packet_count':len(packets),'pattern_count':len(patterns),
            'bpm':int(configs[1][129]),'sample_count':len(roots),
            'unresolved_trims':sum('unresolved' in entry for entry in entries),
            'end_marker_valid':True}

if __name__=='__main__':
    try:
        if len(sys.argv)==2 and sys.argv[1]=='--self-check':
            from po33_decode import self_check
            self_check()
            result={'payload_verified':False,'status':'DECODER_SELF_CHECK_PASS'}
        elif len(sys.argv)==2:
            result=run(sys.argv[1])
        else:
            result={'payload_verified':False,'status':'INVALID_ARGUMENTS'}
        print(json.dumps(result))
        raise SystemExit(0 if result.get('payload_verified') or result['status']=='DECODER_SELF_CHECK_PASS' else 2)
    except (OSError,ValueError,OverflowError) as exc:
        print(json.dumps({'payload_verified':False,'status':'PROTOCOL_NOT_VERIFIED',
                          'detail':str(exc)[:300]}))
        raise SystemExit(2)
