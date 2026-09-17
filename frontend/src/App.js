import SimilarSearch from "./pages/SimilarSearch";
import OutfitRecommendation from "./pages/OutfitRecommendation";
import TripPlanner from "./pages/TripPlanner";
import Dashboard from "./pages/Dashboard";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Wardrobe from "./pages/Wardrobe";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" />} />
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
