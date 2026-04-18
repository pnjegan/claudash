# docs/homebrew/claudash.rb
# Homebrew formula for Claudash
# Install via:
#   brew tap pnjegan/claudash
#   brew install claudash
#
# Or one-liner:
#   brew install pnjegan/claudash/claudash
#
# MAINTAINER NOTE: when bumping the version, regenerate the sha256 with:
#   curl -sL https://github.com/pnjegan/claudash/archive/refs/tags/vX.Y.Z.tar.gz | sha256sum
# GitHub can occasionally regenerate release tarballs; if brew install
# fails with a sha mismatch, recompute and update this file.

class Claudash < Formula
  desc "Claude Code usage intelligence dashboard — detect waste, generate fixes, measure outcomes"
  homepage "https://github.com/pnjegan/claudash"
  url "https://github.com/pnjegan/claudash/archive/refs/tags/v3.3.1.tar.gz"
  sha256 "422c0aecbe8c256d1a53945c2c35d49988f9707e55b1cbc52db8cee411e40e79"
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
