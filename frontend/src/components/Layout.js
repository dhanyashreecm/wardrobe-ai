import Sidebar from "./Sidebar";
import "../App.css";

function Layout({ children }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-content">{children}</main>
    </div>
  );
}

export default Layout;
