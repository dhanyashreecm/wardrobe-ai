content = '''import { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

function Register() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (!name || !email || !password) {
      setError("All fields are required");
      return;
    }

    try {
      const res = await axios.post("http://localhost:5001/api/register", {
        name, email, password
      });
      if (res.data.success) {
        navigate("/login");
      }
    } catch (err) {
      setError(err.response?.data?.message || "Registration failed");
    }
  };

  return (
    <div>
      <h2>Register</h2>
      <form onSubmit={handleSubmit}>
        <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} /><br/>
        <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} /><br/>
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} /><br/>
        <button type="submit">Register</button>
      </form>
      {error && <p style={{color: "red"}}>{error}</p>}
    </div>
  );
}

export default Register;
'''

with open('Register.js', 'w') as f:
    f.write(content)

print("Register.js created")
