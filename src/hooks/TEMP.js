import { useState, useEffect } from "react";

const baseUrl = 'http://localhost:3001/';

export const useFetch = (id, data, endpoint, method) => {
  const [result, setResult] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const url = `${baseUrl}${endpoint}${id ? `/${id}` : ''}`;
        const options = {
          method: method,
          headers: {
            "Content-Type": "application/json",
          },
        };

        if (method === "POST") {
          options.body = JSON.stringify(data);
        }

        const response = await fetch(url, options);
        const jsonData = await response.json();
        console.log("Response data:", jsonData);

        setResult(jsonData);
        if (response.ok) {
          // Request was successful
        } else {
          throw new Error("Request failed");
        }
      } catch (err) {
        console.error("Request error:", err);
        // Provide feedback to the user about the request failure
      }
    };

    fetchData();
  }, [id, data, endpoint, method]);

  return { result };
};
