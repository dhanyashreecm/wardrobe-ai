import SimilarSearch from "./pages/SimilarSearch";
import OutfitRecommendation from "./pages/OutfitRecommendation";
import TripPlanner from "./pages/TripPlanner";
import Dashboard from "./pages/Dashboard";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Wardrobe from "./pages/Wardrobe";

// Gender selection now lives directly on the Login page (see
// Login.js) instead of a separate screen shown before it - "/" just
// goes straight there. (pages/GenderGate.js still exists but is no
// longer routed to; safe to delete later if you don't want the
// unused file around.)

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/similar" element={<SimilarSearch />} />
        <Route
          path="/recommend"
          element={<OutfitRecommendation />}
        />
        <Route path="/wardrobe" element={<Wardrobe />} />
        <Route path="/trip" element={<TripPlanner />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
