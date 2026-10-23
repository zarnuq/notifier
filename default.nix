{ pkgs ? import <nixpkgs> { } }:

let
  python = pkgs.python3.withPackages (ps: [ ps.playwright ]);

  # menu.py needs no browser, but sharing one interpreter keeps the closure
  # single and the two wrappers identical apart from the script they run.
  tool = name: script: extra:
    pkgs.writeShellApplication {
      inherit name;
      text = extra + ''
        exec ${python}/bin/python "$HOME/facebook-notifier/${script}" "$@"
      '';
    };
in
pkgs.symlinkJoin {
  name = "facebook-notifier-tools";
  paths = [
    (tool "facebook-notifier" "monitor.py" ''
      # NixOS can't run Playwright's own downloaded Chromium; use the nixpkgs build.
      export PLAYWRIGHT_BROWSERS_PATH=${pkgs.playwright-driver.browsers}
      export PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=true
    '')
    (tool "psu-menu" "menu.py" "")
  ];
}
