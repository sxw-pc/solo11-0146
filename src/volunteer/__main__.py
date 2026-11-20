import argparse,json
from pathlib import Path
from . import call,credential,attendance,beneficiary,report
from .store import connect

def main(argv=None):
    p=argparse.ArgumentParser(prog='volunteer');sp=p.add_subparsers(dest='command',required=True)
    for name in ('init','import-call','import-skill','import-attendance','import-beneficiary','report','demo'):
        q=sp.add_parser(name);q.add_argument('--db',default='data/demo.sqlite')
        if name.startswith('import-'):q.add_argument('--input',required=True)
        if name=='report':q.add_argument('--as-of',required=True)
    a=p.parse_args(argv);db=connect(a.db)
    try:
        if a.command=='init':result={'initialized':True,'db':a.db}
        elif a.command.startswith('import-'):
            data=json.loads(Path(a.input).read_text(encoding='utf-8'))
            result={'import-call':call,'import-skill':credential,'import-attendance':attendance,'import-beneficiary':beneficiary}[a.command].ingest(db,data)
        elif a.command=='report':result=report.decide(db,a.as_of)
        else:
            root=Path(__file__).resolve().parents[2]
            for name,mod in [('call_good.json',call),('skill_good.json',credential),('attend_good.json',attendance),
                             ('invite_frozen.json',beneficiary),('delivery_dual.json',beneficiary),
                             ('survey_complete.json',beneficiary),('contracts_two.json',beneficiary)]:
                mod.ingest(db,json.loads((root/'fixtures'/'volunteer'/name).read_text(encoding='utf-8')))
            result=report.decide(db,'2026-11-17T18:00:00Z')
        print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0
    except (ValueError,KeyError) as e:print(json.dumps({'error':str(e)},ensure_ascii=False));return 2
    finally:db.close()

if __name__=='__main__':raise SystemExit(main())
