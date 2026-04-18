# docs/homebrew/claudash.rb
# Homebrew formula for Claudash
# Install via:
#   brew tap pnjegan/claudash
#   brew install claudash
#
# Or one-liner:
#   brew install pnjegan/claudash/claudash
#
# MAINTAINER NOTE: after cutting a release tag on GitHub, replace the
# sha256 PLACEHOLDER below with the tarball hash. Get it with:
#   curl -sL https://github.com/pnjegan/claudash/archive/refs/tags/v3.3.1.tar.gz | sha256sum

class Claudash < Formula
  desc "Claude Code usage intelligence dashboard — detect waste, generate fixes, measure outcomes"
  homepage "https://github.com/pnjegan/claudash"
  url "https://github.com/pnjegan/claudash/archive/refs/tags/v3.3.1.tar.gz"
  sha256 "PLACEHOLDER_REPLACE_WITH_REAL_SHA256"
  license "MIT"

  depends_on "python@3.11"
  depends_on "node" => :optional  # only needed for npx install method

  def install
    # Install Python scripts and supporting assets
    libexec.install Dir["*.py"]
    libexec.install "templates" if Dir.exist?("templates")
    libexec.install "tools"     if Dir.exist?("tools")
    libexec.install "static"    if Dir.exist?("static")
    libexec.install "bin"       if Dir.exist?("bin")

    # Create wrapper script
    (bin/"claudash").write <<~EOS
      #!/bin/bash
      exec python3 "#{libexec}/cli.py" "$@"
    EOS
  end

  def caveats
    <<~EOS
      Claudash reads Claude Code session files from:
        macOS:   ~/.claude/projects/
        Linux:   ~/.claude/projects/

      To start the dashboard:
        claudash dashboard

      First time setup:
        claudash init

      All data stays local. Nothing is uploaded.
    EOS
  end

  test do
    system "#{bin}/claudash", "--version"
  end
end
