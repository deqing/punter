import signal
import sys
from docopt import docopt
from worker import WebWorker


def main():
    """Punter command-line interface.

    Usage:
      cli.py <websites> <leagues> [options]

    Options:
      --all                     Get all leagues
      --get-only                Don't merge and print matches
      --print                   Don't get latest odds, just print out based on saved odds
      --print-betfair-only      Don't print other results
      --send-email-api          Send email by MailGun's restful api
      --send-email-smtp         Send email by SMTP (note: not working in GCE)
      --send-email-when-found   Send email by api when returns bigger than 99.5
      --loop=<n>                Repeat every n minutes [default: 0]
      --ask-gce=<websites>      Read from GCE for these websites
      --gce-ip=<ip>             GCE instance IP
      --bonus                   Calculate and print bonus profit
      --calc-best=<odds>        Calculate and print best profit
      --calc-back=<odd>         Calculate and print real back odd
      --highlight=<string>      monitor one match
      --betfair-limits=<number> highlight when biggest back and lay less than
      --betfair                 including betfair back odds
      --exclude=<websites>      excluding websites
      --compare-ladbrokes       read urls from ladbrokes.txt, compare with betfair and print
      --compare-classicbet      read urls from classicbet.txt, compare with betfair and print
      --compare-race            read urls from race.txt and compare

    Example:
      cli.py luxbet,crownbet a
      cli.py all eng,uefa
      cli.py bet365,ubet fra --ask-gce=bet365 --gce-ip=1.2.3.4 --loop=10
      cli.py a a --calc-best=2.10,3.5,3.75
      cli.py a a --calc-back=4.2
      cli.py bet365 gem "Adelaide Utd,Central Coast,,3.55,1.0"   # draw > 3.55 or lost > 1.0
      cli.py bet365 eng --betfair-limits=1,2,0.05,-5  # 1 < lay odd < 2, diff <= 0.05, profit > -5
      cli.py a a --compare-ladbrokes
    """
    worker = False

    def signal_handler(_, __):
        print('You pressed Ctrl+C!')
        if worker and worker.driver:
            worker.driver.quit()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    args = docopt(str(main.__doc__))
    worker = WebWorker(is_get_data=not args['--print'] and not args['--print-betfair-only'],
                       keep_driver_alive=False)

    if args['--bonus']:
        worker.calc_bonus_profit(args['<websites>'])
    elif args['--calc-best'] is not None:
        o1, o2, o3 = args['--calc-best'].split(',')
        worker.calc_best_shot(float(o1), float(o2), float(o3))
    elif args['--calc-back'] is not None:
        worker.calc_real_back_odd(args['--calc-back'])
    elif args['--compare-ladbrokes']:
        worker.compare_back_and_lay('ladbrokes', int(args['--loop']))
    elif args['--compare-classicbet']:
        worker.compare_back_and_lay('classicbet', int(args['--loop']))
    elif args['--compare-race']:
        worker.compare_with_race()
    else:
        worker.run(
            websites_str=args['<websites>'],
            leagues_str=args['<leagues>'],
            is_get_only=args['--get-only'],
            is_send_email_api=args['--send-email-api'],
            is_send_email_smtp=args['--send-email-smtp'],
            is_send_email_when_found=args['--send-email-when-found'],
            loop_minutes=int(args['--loop']),
            ask_gce=args['--ask-gce'],
            gce_ip=args['--gce-ip'],
            highlight=args['--highlight'],
            betfair_limits=args['--betfair-limits'],
            is_betfair=(args['--betfair']),
            exclude=(args['--exclude']),
            print_betfair_only=(args['--print-betfair-only'])
        )


if __name__ == "__main__":
    main()
