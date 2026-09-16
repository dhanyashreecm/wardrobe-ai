import SimilarSearch from "./pages/SimilarSearch";
import OutfitRecommendation from "./pages/OutfitRecommendation";
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
	<Route path="/similar" element={<SimilarSearch />} />	
        <Route
  path="/recommend"
  element={<OutfitRecommendation />}
/>
        <Route path="/wardrobe" element={<Wardrobe />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
