{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: [ ps.playwright ps.pytest ]))
  ];

  # NixOS can't run Playwright's own downloaded Chromium; use the nixpkgs build.
  PLAYWRIGHT_BROWSERS_PATH = pkgs.playwright-driver.browsers;
  PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "true";
}
