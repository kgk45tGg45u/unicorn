Rails.application.routes.draw do
  devise_for :users
  # Define your application routes per the DSL in https://guides.rubyonrails.org/routing.html

  # Defines the root path route ("/")
  # root "articles#index"

  get "dashboard", to: "pages#userdashboard"
  root :to => redirect("/users/sign_in")
  
end
