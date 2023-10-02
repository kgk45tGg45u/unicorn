class CreateFundtwos < ActiveRecord::Migration[7.0]
  def change
    create_table :fundtwos do |t|
      t.integer :balance

      t.timestamps
    end
  end
end
