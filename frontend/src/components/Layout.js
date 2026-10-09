import Sidebar from "./Sidebar";
import MobileNav from "./MobileNav";
import "../App.css";

function Layout({ children }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <MobileNav />
      <main className="app-content">{children}</main>
    </div>
  );
}

export default Layout;
