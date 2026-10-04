// GET /api/status: tells the app whether Claude notes are available on this deployment.
module.exports = (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  res.status(200).json({
    claude: Boolean(process.env.ANTHROPIC_API_KEY),
    model: process.env.SCREENTEST_MODEL || "claude-sonnet-5-5",
    pass: Boolean(process.env.NOTES_PASSCODE),
  });
};
