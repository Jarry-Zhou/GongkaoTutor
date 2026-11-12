"""Download pinned national exam data for local study and activate it atomically."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import Application
import national_bank as bank


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    parser.add_argument('--cache',type=Path,help='Optional existing verified upstream cache')
    parser.add_argument('--replace',action='store_true',help='Archive current question bank and activate national questions')
    parser.add_argument('--restore',action='store_true',help='Restore the previously visible bank without deleting data')
    args=parser.parse_args();app=Application(args.data_dir)
    if args.restore:
        result=bank.restore(app);print('已恢复旧题库，新真题仍保留在本机。');print(json.dumps(result,ensure_ascii=False));return
    current=bank.status(app)
    if current['installed']:
        print('当前国考真题版本已经安装，保留已有人工修订与练习记录。');return
    if app.catalog_questions() and not args.replace:
        print('已检测到现有题库，保留不变。可在“我的题库”确认替换，或明确使用--replace。');return
    def progress(phase,done,total):print(f'{phase}：{done}/{total}',flush=True)
    qs,report=bank.prepare(app,seed=args.cache,progress=progress)
    installed=bank.install(app,qs,report,replace=args.replace)
    print(json.dumps({'installed':True,'report':report,'archived':len(installed.get('hidden_question_ids',[]))},ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:main()
    except Exception as error:
        print('真题下载或校验未完成，现有题库保留。可重新运行复用已下载文件。',file=sys.stderr)
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        raise SystemExit(1)
