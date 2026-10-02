async function registerUser() {

    const name = document.getElementById("regName").value.trim();
    const email = document.getElementById("regEmail").value.trim().toLowerCase();
    const password = document.getElementById("regPassword").value.trim();

    const response = await fetch("/register",{
        method:"POST",
        headers:{
            "Content-Type":"application/json"
        },
        body:JSON.stringify({
            name,
            email,
            password
        })
    });

    const data = await response.json();

    if(data.status=="success"){
        alert("Registration Successful");
        window.location.href="login.html";
    }else{
        alert(data.message);
    }

}


async function loginUser() {
    console.log("Login button clicked");

    const email = document.getElementById("loginEmail").value.trim().toLowerCase();
    const password = document.getElementById("loginPassword").value.trim();

    if (!email || !password) {
        alert("Email and password are required");
        return;
    }

    try {
        const response = await fetch("/login", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                email,
                password
            })
        });

        const data = await response.json();

        console.log("Login response:", data);

        if (data.status === "success") {

            // Save JWT token
            localStorage.setItem("token", data.token);

            // Save user information returned by backend
            localStorage.setItem("user", JSON.stringify(data.user));

            console.log("User saved:", data.user);

            alert("Login Successful");

            window.location.href = "index.html";

        } else {
            alert(data.message || "Login failed");
        }

    } catch (error) {
        console.error("Login error:", error);
        alert("Unable to connect to server");
    }
}


