// Register Chart.js elements once to keep components lean
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from "chart.js";

Chart.register(ArcElement, BarElement, LineElement, CategoryScale, LinearScale, PointElement, Tooltip, Filler, Legend);

export { Chart };
