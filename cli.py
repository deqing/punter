import signal
import sys
from docopt import docopt

from worker import WebWorker


def main():
    """Punter command-line interface.

    Usage:
      cli.py <websites> [options]

    Options:
      --all                     Get all leagues
      --a                       Get A-league
      --arg                     Get Argentina league
      --eng                     Get EPL
      --ita                     Get Italy league
      --liga                    Get La Liga
      --get-only                Don't merge and print matches
      --print                   Don't get latest odds, just print out based on saved odds
      --send-email-api          Send email by MailGun's restful api
      --send-email-smtp         Send email by SMTP (note: not working in GCE)
      --send-email-when-found   Send email by api when returns bigger than 99.5
      --loop=<n>                Repeat every n minutes [default: 0]
      --ask-gce=<websites>      Read from GCE for these websites
      --gce-ip=<ip>             GCE instance IP

    Example:
      cli.py luxbet,crownbet --a
      cli.py all --eng
      cli.py bet365,ubet --eng --ask-gce=bet365 --loop=10
    """
    worker = False

    def signal_handler(_, __):
        print('You pressed Ctrl+C!')
        if worker and worker.driver:
            worker.driver.quit()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    args = docopt(str(main.__doc__))
    worker = WebWorker(is_get_data=not args['--print'], keep_driver_alive=False)
    worker.run(
        websites=args['<websites>'],
        is_get_a=args['--a'],
        is_get_arg=args['--arg'],
        is_get_eng=args['--eng'],
        is_get_ita=args['--ita'],
        is_get_liga=args['--liga'],
        is_get_only=args['--get-only'],
        is_send_email_api=args['--send-email-api'],
        is_send_email_smtp=args['--send-email-smtp'],
        is_send_email_when_found=args['--send-email-when-found'],
        loop_minutes=int(args['--loop']),
        ask_gce=args['--ask-gce'],
        gce_ip=args['--gce-ip'],
    )


if __name__ == "__main__":
    main()
