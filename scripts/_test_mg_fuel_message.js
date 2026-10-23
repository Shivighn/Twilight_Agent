const { login } = require('../src/mgFuelSavings/authClient');
const { getCurrentMonthRangeIST } = require('../src/mgFuelSavings/dateRange');
const { fetchTotalSavings } = require('../src/mgFuelSavings/savingsFetcher');
const { fetchAnomalyCount } = require('../src/mgFuelSavings/anomalyFetcher');
const { buildAnomalyMessage, buildSavingsMessage } = require('../src/mgFuelSavings/messageBuilder');

(async () => {
  const session = await login();
  const { yearMonth, fromISO, toISO } = getCurrentMonthRangeIST();

  const totalSavings = await fetchTotalSavings(yearMonth, session);
  const { anomalyCount, pendingMileageCount } = await fetchAnomalyCount(fromISO, toISO, session);
  console.log({ totalSavings, anomalyCount, pendingMileageCount });

  const content = anomalyCount > 0
    ? buildAnomalyMessage(anomalyCount)
    : buildSavingsMessage(totalSavings, pendingMileageCount);
  console.log('\n--- MESSAGE (NOT sent — dry run only) ---\n' + content.text + '\n------------------------------------------');
})().catch((err) => {
  console.error('FAILED', err.message);
  process.exit(1);
});
