import { Configuration, FrontendApi } from "@ory/client"

const ory = new FrontendApi(
    new Configuration({
        basePath: "https://<your-project-slug>.projects.oryapis.com",
        baseOptions: {
            withCredentials: true, // Essential for cookies/sessions
        },
    })
)

export default ory