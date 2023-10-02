class PagesController < ApplicationController

  def userdashboard
    fundone = Fundone.new(balance: -200)
    fundtwo = Fundtwo.new(balance: 200)

    @balance = fundtwo.balance
  end
end
