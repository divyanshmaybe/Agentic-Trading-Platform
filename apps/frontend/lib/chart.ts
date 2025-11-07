// Register Chart.js elements once to keep components lean
import {
  ArcElement,
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from "chart.js";

Chart.register(ArcElement, LineElement, CategoryScale, LinearScale, PointElement, Tooltip, Filler, Legend);

export { Chart };
